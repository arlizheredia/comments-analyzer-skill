#!/usr/bin/env python3
"""Normalize social media comments into one canonical JSON file.

Accepts, in any mix:
  * raw JSON results of Agensi data tools (Instagram, TikTok, Facebook comment
    tools: provider-native shapes, paginated pages, nested replies),
  * JSON or CSV exports of the Social Comments Analyzer web app,
  * generic CSV / JSON / JSONL files with comment-like columns,
  * files already produced by this script (they are merged and de-duplicated).

Usage:
  normalize.py INPUT [INPUT ...] -o comments.json [--platform tiktok] [--post URL]
  An INPUT may be written as PATH::POST_URL to tag its comments with a post.

Standard library only. No network access. Writes only the -o file.
"""
import argparse
import csv
import datetime as dt
import io
import json
import re
import sys

SCHEMA = "social-comments/v1"

# --- field aliases (data) ---------------------------------------------------
TEXT_KEYS = ["text", "comment_text", "commentText", "comment", "message", "body", "content",
             "textOriginal", "textDisplay", "texto", "comentario"]
ID_KEYS = ["id", "cid", "comment_id", "commentId", "pk", "legacy_fbid", "feedback_id", "commentID"]
PARENT_KEYS = ["parentId", "parent_id", "parent_comment_id", "parentCommentId", "reply_to_comment_id",
               "repliedToCommentId", "replied_to_comment_id", "reply_id", "id_padre"]
AUTHOR_OBJ_KEYS = ["user", "owner", "author", "from", "profile", "commenter", "creator"]
AUTHOR_NAME_KEYS = ["username", "unique_id", "uniqueId", "nickname", "name", "full_name", "display_name",
                    "displayName", "title"]
AUTHOR_FLAT_KEYS = ["authorName", "author_name", "ownerUsername", "username", "user_name", "profileName",
                    "author", "authorDisplayName", "autor"]
AUTHOR_ID_KEYS = ["id", "pk", "uid", "user_id", "sec_uid", "secUid"]
AUTHOR_FLAT_ID_KEYS = ["authorId", "author_id", "ownerId", "user_id", "userId", "profileId", "id_autor"]
AUTHOR_URL_KEYS = ["authorUrl", "author_url", "profileUrl", "profile_url", "ownerProfileUrl", "perfil_autor"]
DATE_KEYS = ["createdAt", "created_at", "create_time", "createTime", "created_time", "createdTime",
             "timestamp", "taken_at", "publishedAt", "published_at", "date", "time", "fecha_iso", "fecha"]
LIKE_KEYS = ["likes", "like_count", "likeCount", "likesCount", "digg_count", "diggCount",
             "comment_like_count", "reactions", "reaction_count", "reactionCount", "reactions_count",
             "reacciones"]
REPLY_COUNT_KEYS = ["repliesCount", "reply_count", "replyCount", "replies_count", "reply_comment_total",
                    "child_comment_count", "comments_count", "respuestas"]
NESTED_KEYS = ["replies", "children", "child_comments", "reply_comment", "preview_child_comments",
               "comment_replies", "threaded_replies", "replyComments"]
LINK_KEYS = ["permalink", "url", "share_url", "commentUrl", "comment_url", "link", "enlace"]
POST_KEYS = ["postUrl", "post_url", "media_url", "video_url", "postId", "post_id", "media_id", "aweme_id"]
PLATFORM_KEYS = ["platform", "plataforma", "network", "source_platform"]

# CSV headers of the web app (Spanish labels) -> canonical keys
CSV_HEADER_MAP = {
    "id": "id", "id padre": "parentId", "parent_id": "parentId", "autor": "authorName",
    "id autor": "authorId", "perfil autor": "authorUrl", "fecha iso": "createdAt", "fecha_iso": "createdAt",
    "comentario": "text", "texto": "text", "reacciones": "likes", "respuestas": "repliesCount",
    "enlace": "permalink", "plataforma": "platform", "fuente": "source",
}

PLATFORM_NAMES = {"facebook": "facebook", "fb": "facebook", "instagram": "instagram", "ig": "instagram",
                  "tiktok": "tiktok", "tt": "tiktok", "youtube": "youtube", "x": "x", "twitter": "x"}


def first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def as_int(v):
    if isinstance(v, bool) or v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, dict):  # e.g. {"count": 12} or {"summary": {"total_count": 3}}
        return as_int(first(v, ["count", "total_count", "total"]) or first(v.get("summary", {}) or {}, ["total_count"]))
    s = str(v).strip().lower().replace(",", "").replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)([km]?)$", s)
    if not m:
        return 0
    n = float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6}[m.group(2)]
    return int(n)


def to_iso(v):
    """Epoch seconds/ms or a date string -> ISO 8601 UTC string, else ''."""
    if v in (None, ""):
        return ""
    try:
        if isinstance(v, (int, float)) or re.fullmatch(r"\d{9,13}(\.\d+)?", str(v).strip()):
            n = float(v)
            if n > 1e12:
                n /= 1000.0
            return dt.datetime.fromtimestamp(n, tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
        s = str(v).strip()
        s2 = s.replace("Z", "+00:00")
        s2 = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s2)  # +0000 -> +00:00
        d = dt.datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return d.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return ""


def detect_platform(hint, url, raw):
    if hint:
        return PLATFORM_NAMES.get(hint.lower(), hint.lower())
    p = first(raw, PLATFORM_KEYS) if isinstance(raw, dict) else None
    if isinstance(p, str) and p.lower() in PLATFORM_NAMES:
        return PLATFORM_NAMES[p.lower()]
    u = (url or "").lower()
    for dom, name in (("tiktok", "tiktok"), ("instagram", "instagram"), ("facebook", "facebook"),
                      ("fb.com", "facebook"), ("fb.watch", "facebook"), ("youtu", "youtube")):
        if dom in u:
            return name
    if isinstance(raw, dict):
        keys = set(raw)
        if keys & {"digg_count", "aweme_id", "cid", "reply_comment_total"}:
            return "tiktok"
        if keys & {"comment_like_count", "child_comment_count", "pk"}:
            return "instagram"
        if keys & {"legacy_fbid", "feedback_id", "reaction_count"}:
            return "facebook"
    return ""


def author_of(raw):
    name = aid = aurl = ""
    for k in AUTHOR_OBJ_KEYS:
        obj = raw.get(k)
        if isinstance(obj, dict):
            name = str(first(obj, AUTHOR_NAME_KEYS) or "")
            aid = str(first(obj, AUTHOR_ID_KEYS) or "")
            aurl = str(first(obj, ["url", "profile_url", "link"]) or "")
            if name or aid:
                break
    if not name:
        v = first(raw, AUTHOR_FLAT_KEYS)
        name = v if isinstance(v, str) else ""
    aid = aid or str(first(raw, AUTHOR_FLAT_ID_KEYS) or "")
    aurl = aurl or str(first(raw, AUTHOR_URL_KEYS) or "")
    return name.strip(), aid, aurl


def text_of(raw):
    v = first(raw, TEXT_KEYS)
    if isinstance(v, dict):  # {"text": "..."} wrappers
        v = first(v, ["text", "body"])
    return v if isinstance(v, str) else None


def looks_like_comment(d):
    if not isinstance(d, dict):
        return False
    t = text_of(d)
    if t is None:
        return False
    return bool(first(d, ID_KEYS) or author_of(d)[0] or first(d, DATE_KEYS))


def to_comment(raw, ctx, parent_id=""):
    name, aid, aurl = author_of(raw)
    post_url = ctx.get("post") or ""
    pv = first(raw, POST_KEYS)
    if not post_url and isinstance(pv, str) and pv.startswith("http"):
        post_url = pv
    platform = detect_platform(ctx.get("platform"), post_url or str(first(raw, LINK_KEYS) or ""), raw) \
        or ctx.get("detected") or ""
    return {
        "id": str(first(raw, ID_KEYS) or ""),
        "parentId": str(first(raw, PARENT_KEYS) or parent_id or ""),
        "platform": platform,
        "postUrl": post_url,
        "postId": str(pv) if pv and not str(pv).startswith("http") else "",
        "authorName": name,
        "authorId": aid,
        "authorUrl": aurl,
        "text": text_of(raw) or "",
        "createdAt": to_iso(first(raw, DATE_KEYS)),
        "likes": as_int(first(raw, LIKE_KEYS)),
        "repliesCount": as_int(first(raw, REPLY_COUNT_KEYS)),
        "permalink": str(first(raw, LINK_KEYS) or ""),
        "source": ctx.get("source", ""),
    }


def walk(node, ctx, out, parent_id="", depth=0):
    """Find comment-like dicts anywhere in a JSON tree (pages, wrappers, nesting)."""
    if depth > 12:
        return
    if isinstance(node, list):
        for item in node:
            walk(item, ctx, out, parent_id, depth + 1)
        return
    if not isinstance(node, dict):
        return
    if node.get("schema") == SCHEMA and isinstance(node.get("comments"), list):
        out.extend(dict(c) for c in node["comments"])  # already normalized
        return
    if not ctx.get("detected"):
        ctx["detected"] = detect_platform(ctx.get("platform"), first(node, ["url", "postUrl", "post_url"]) or "", node)
    kids = node.get("comments")
    if isinstance(kids, list) and any(looks_like_comment(k) for k in kids[:5]):
        # a post (or a page of results) wrapping its comments: tag them with the post URL
        sub = dict(ctx)
        url = first(node, ["url", "postUrl", "post_url", "permalink", "share_url"])
        if not sub.get("post") and isinstance(url, str) and url.startswith("http"):
            sub["post"] = url
            sub["detected"] = detect_platform(ctx.get("platform"), url, node) or ctx.get("detected")
        walk(kids, sub, out, "", depth + 1)
        return
    if looks_like_comment(node):
        c = to_comment(node, ctx, parent_id)
        out.append(c)
        for k in NESTED_KEYS:
            if k in node:
                walk(node[k], ctx, out, c["id"] or parent_id, depth + 1)
        return
    for v in node.values():
        if isinstance(v, (dict, list)):
            walk(v, ctx, out, parent_id, depth + 1)


def read_csv(text, ctx):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    out = []
    for r in rows:
        rec = {}
        for k, v in r.items():
            if k is None:
                continue
            key = k.strip().lstrip("﻿")
            rec[CSV_HEADER_MAP.get(key.lower(), key)] = v
        if text_of(rec) is not None:
            out.append(to_comment(rec, ctx, ""))
    return out


def load(path, ctx):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()
    stripped = text.lstrip()
    if path.lower().endswith((".csv", ".tsv")) or (stripped and stripped[0] not in "[{"):
        return read_csv(text, ctx)
    out = []
    try:
        walk(json.loads(text), ctx, out)
    except json.JSONDecodeError:  # JSON Lines
        for line in text.splitlines():
            line = line.strip()
            if line:
                try:
                    walk(json.loads(line), ctx, out)
                except json.JSONDecodeError:
                    continue
    return out


def finalize(comments):
    seen, result = set(), []
    for c in comments:
        c.setdefault("platform", "")
        c["text"] = (c.get("text") or "").strip()
        if not c["text"] and not c.get("id"):
            continue
        key = (c.get("platform"), c.get("id")) if c.get("id") else \
            ("~", c.get("authorName"), c["text"], c.get("createdAt"))
        if key in seen:
            continue
        seen.add(key)
        result.append(c)
    for i, c in enumerate(result, 1):
        if not c.get("id"):
            c["id"] = "local-%d" % i
    ids = {c["id"] for c in result}
    for c in result:  # a parent pointing at the post itself is a top-level comment
        if c.get("parentId") and c["parentId"] not in ids and c["parentId"] == c.get("postId"):
            c["parentId"] = ""
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="files; PATH::POST_URL tags a file's comments with a post")
    ap.add_argument("-o", "--output", required=True, help="output JSON path")
    ap.add_argument("--platform", help="force platform: instagram, tiktok, facebook")
    ap.add_argument("--post", help="post URL applied to inputs without one")
    a = ap.parse_args(argv)

    all_comments, report = [], []
    for spec in a.inputs:
        path, _, post = spec.partition("::")
        ctx = {"platform": a.platform, "post": post or a.post or "", "source": path.rsplit("/", 1)[-1]}
        try:
            found = load(path, ctx)
        except OSError as e:
            print("error: cannot read %s: %s" % (path, e), file=sys.stderr)
            return 2
        report.append((path, len(found)))
        all_comments.extend(found)

    comments = finalize(all_comments)
    payload = {"schema": SCHEMA, "generatedAt": to_iso(dt.datetime.now(dt.timezone.utc).timestamp()),
               "count": len(comments), "comments": comments}
    with open(a.output, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)

    for path, n in report:
        print("%6d  %s" % (n, path))
    by_platform = {}
    for c in comments:
        by_platform[c["platform"] or "unknown"] = by_platform.get(c["platform"] or "unknown", 0) + 1
    print("total %d unique comments -> %s  %s" % (len(comments), a.output, json.dumps(by_platform)))
    if not comments:
        print("warning: no comments found. Check that the input holds comment objects with a text field.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

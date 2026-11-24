#!/usr/bin/env python3
"""Analyze normalized comments: sentiment, activity, authors, words, emojis,
hashtags, mentions, questions, top comments, per-post and per-platform stats.

Usage:
  analyze.py comments.json -o analysis.json [--enriched enriched.json]
             [--labels labels.json] [--team "brand,@handle"] [--focus-name "Brand X"]
             [--digest digest.jsonl --digest-size 400] [--top 15]

  comments.json  output of normalize.py
  --labels       optional JSON written by the agent after reading the digest:
                 {"<comment id>": {"sentiment": "positive|neutral|negative",
                                    "focus": true, "topic": "delivery"}, ...}
                 Agent labels override the lexicon sentiment.
  --team         names/handles of the brand's own accounts (comma separated):
                 their comments are flagged, and questions with no team reply
                 are listed as unanswered.
  --digest       writes compact JSON Lines (id, author, text, likes, sentiment)
                 for the agent to read, classify and quote.

Prints a short Markdown summary. Standard library only, no network.
"""
import argparse
import collections
import datetime as dt
import json
import re
import sys
import unicodedata

# --- lexicons (data, ported from the Social Comments Analyzer web app) -------
STOP = set((
    "sido estoy está están tengo tenía hemos he a al algo algunas algunos ante antes como con contra cual cuando de "
    "del desde donde durante e el ella ellas ellos en entre era eran es esa esas ese eso esos esta estaba estado "
    "estan estar estas este esto estos fue fueron ha hace hacia han hasta hay la las le les lo los mas me mi mis "
    "mucho muy nada ni no nos nosotros o os otra otro para pero poco por porque que quien se sea ser si sin sobre "
    "son su sus tambien te tiene tienen todo todos tu tus un una uno unos usted ustedes y ya yo vos q k pq xq x d "
    "tb tmb jaja jajaja jajajaja jeje ok asi aqui ahi solo cada mismo misma hoy van va voy será sí también así "
    "aquí ahí más qué cómo cuál dónde él tú mí "
    "the a an and or but if of to in on at by for with about as is are was were be been being have has had do "
    "does did not no yes it its this that these those i you he she we they me my your our their them his her so "
    "just than then there here what which who whom will would can could should from up out into over all any "
    "some more most very too also get got im it's i'm don't dont lol "
    "o os um uma de da do das dos em no na nos nas por para com que se mais muito é e eu você voce ele ela").split())
POS = set((
    "gusta gustó gusto gustan gustaron bueno buena buenos buenas excelente excelentes genial gracias increíble increible hermoso hermosa bonito "
    "bonita lindo linda perfecto perfecta encanta encantó amo amor felicidades felicitaciones bien mejor mejores "
    "maravilloso maravillosa fantástico fantastico feliz super súper recomendado recomiendo espectacular "
    "bendiciones éxito exito apoyo top crack bravo precioso preciosa divino fascinante orgullo calidad rápido "
    "rapido agradecido agradecida puntual puntuales eficiente eficientes amable amables atento atenta "
    "satisfecho satisfecha contento contenta fresco fresca confiable seguro segura profesional impecable "
    "encantado encantada agradezco buenísimo buenisimo riquísimo riquisimo rico rica delicioso deliciosa "
    "great good love loved loving awesome amazing excellent thanks thank nice beautiful perfect best happy "
    "wonderful cool congrats congratulations recommend fast friendly fresh reliable fantastic incredible "
    "obrigado obrigada ótimo otimo lindo maravilha parabéns parabens adorei amei").split())
NEG = set((
    "malo mala malos malas pésimo pesimo pésima pesima horrible terrible odio asco fraude estafa estafadores "
    "mentira mentiras mentirosos peor basura triste decepción decepcion decepcionado decepcionada problema "
    "problemas queja nunca lamentable vergüenza verguenza robo ladrones caro lento error falla fallas mal tarde "
    "lenta lentos lentas molesto molesta indignante abuso denuncia cancelar falló fallo fallaron tardanza demora demoras retraso "
    "podrido vencido roto rota dañado dañada defectuoso incompleto equivocado asqueroso engaño estafaron robaron "
    "irresponsable incumplimiento pérdida perdido frustrante insatisfecho descontento inaceptable desastre fatal "
    "nefasto mediocre grosero maltrato reclamo devolución devolucion reembolso jamás jamas cobraron abusivo feo "
    "bad worst hate hated awful scam fraud poor sad angry disappointed disappointing problem slow broken fake "
    "never terrible useless refund rude late waste ugly horrible "
    "ruim péssimo pessimo golpe lixo odeio nunca triste").split())
NEG_STEMS = ("desagrad tardanz demor retras malolient podrid apest asquer estaf engan defectuos incumpl irrespons "
             "decepcion frustr insatisf descontent indign pesim horribl lamentabl vergonz abusiv fraudul").split()
POS_STEMS = "recomend agradec excelen encant maravill fantast satisf puntual eficien profesional felicit impecabl".split()
ADVERSATIVE = {"pero", "aunque", "embargo", "but", "however", "porém", "porem"}
NEGATORS = {"no", "nunca", "ni", "jamás", "jamas", "not", "never", "sin", "nao", "não", "dont", "don't"}
POS_E = "❤ 😍 🥰 😊 😁 😀 😃 👍 👏 🙌 💯 🔥 🎉 💪 😂 🤣 💙 💚 💛 💜 ♥ 😘 🤩 ✨ 🙏".split()
NEG_E = "😡 😠 🤬 👎 😢 😭 😞 😒 🙄 💩 😤 😔 😩 😫 🤮 😑".split()

TOKEN_RE = re.compile(r"[^\W_][\w'’-]*", re.UNICODE)
HASHTAG_RE = re.compile(r"#[^\W][\w]*", re.UNICODE)
MENTION_RE = re.compile(r"@[\w.]{2,}", re.UNICODE)
URL_RE = re.compile(r"https?://\S+")
EMOJI_RE = re.compile("[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF☀-➿⭐❤♥]")
LABELS = ("positive", "neutral", "negative")


def strip_accents(w):
    return "".join(ch for ch in unicodedata.normalize("NFD", w) if unicodedata.category(ch) != "Mn")


def tokenize(text):
    return TOKEN_RE.findall(URL_RE.sub(" ", (text or "").lower()))


def polarity(w):
    n = strip_accents(w)
    if w in NEG or n in NEG:
        return -1  # negative first: "insatisfecho" must not match "satisf"
    if w in POS or n in POS:
        return 1
    if len(n) >= 5:
        if any(n.startswith(s) for s in NEG_STEMS):
            return -1
        if any(n.startswith(s) for s in POS_STEMS):
            return 1
    return 0


def sentiment(text):
    """Lexicon score: +1 positive term, -1.5 negative term, negation flips,
    terms after 'but/pero' weigh double, emojis +/-1."""
    toks, score, boost = tokenize(text), 0.0, 1
    for i, w in enumerate(toks):
        if w in ADVERSATIVE:
            boost = 2
            continue
        pol = polarity(w)
        if not pol:
            continue
        negated = (i > 0 and toks[i - 1] in NEGATORS) or \
                  (i > 1 and toks[i - 2] in NEGATORS and not polarity(toks[i - 1]))
        v = -pol if negated else pol
        score += (1 if v > 0 else -1.5) * boost
    score = round(score * 2) / 2
    score += sum(1 for e in POS_E if e in text) - sum(1 for e in NEG_E if e in text)
    return ("positive" if score > 0 else "negative" if score < 0 else "neutral"), score


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def norm_handle(s):
    return strip_accents((s or "").lower().lstrip("@").strip())


def enrich(comments, labels, team):
    by_id = {c["id"]: c for c in comments}
    team_set = {norm_handle(t) for t in team if t.strip()}
    for c in comments:
        text = c.get("text") or ""
        lab, score = sentiment(text)
        c["sentimentAuto"] = lab
        c["sentimentScore"] = score
        c["sentiment"] = lab
        c["type"] = "reply" if c.get("parentId") else "comment"
        c["hashtags"] = [h.lower() for h in HASHTAG_RE.findall(text)]
        c["mentions"] = [] if c.get("platform") == "tiktok" else [m[1:] for m in MENTION_RE.findall(text)]
        c["emojis"] = EMOJI_RE.findall(text)
        c["isQuestion"] = "?" in text or "¿" in text
        c["words"] = len(tokenize(text))
        c["isTeam"] = bool(team_set) and (norm_handle(c.get("authorName")) in team_set
                                          or norm_handle(c.get("authorId")) in team_set)
        lb = labels.get(c["id"]) or {}
        if lb.get("sentiment") in LABELS:
            c["sentiment"] = lb["sentiment"]
            c["sentimentSource"] = "agent"
        if "focus" in lb:
            c["focus"] = bool(lb["focus"])
        if lb.get("topic"):
            c["topic"] = str(lb["topic"])
    replied_by_team = {c["parentId"] for c in comments if c.get("isTeam") and c.get("parentId")}
    for c in comments:
        c["answeredByTeam"] = c["id"] in replied_by_team
        if c.get("parentId") and c["parentId"] in by_id and not c.get("replyTo"):
            c["replyTo"] = by_id[c["parentId"]].get("authorName", "")
    return comments


def brief(c, n=280):
    t = c.get("text") or ""
    return {"id": c["id"], "author": c.get("authorName", ""), "platform": c.get("platform", ""),
            "text": t if len(t) <= n else t[:n] + "…", "likes": c.get("likes", 0),
            "sentiment": c.get("sentiment"), "createdAt": c.get("createdAt", ""), "postUrl": c.get("postUrl", "")}


def stats(comments, top):
    n = len(comments)
    sent = collections.Counter(c["sentiment"] for c in comments)
    days, hours, weekdays = collections.Counter(), collections.Counter(), collections.Counter()
    for c in comments:
        d = parse_ts(c.get("createdAt"))
        if d:
            days[d.date().isoformat()] += 1
            hours[d.hour] += 1
            weekdays[d.strftime("%a")] += 1
    authors = collections.Counter(c.get("authorName") or "(unknown)" for c in comments if not c.get("isTeam"))
    words = collections.Counter(w for c in comments
                                for w in tokenize(MENTION_RE.sub(" ", HASHTAG_RE.sub(" ", c.get("text") or "")))
                                if len(w) > 2 and w not in STOP and not w.isdigit()
                                and strip_accents(w) not in STOP and not w.startswith(("@", "#")))
    emojis = collections.Counter(e for c in comments for e in c["emojis"])
    hashtags = collections.Counter(h for c in comments for h in c["hashtags"])
    mentions = collections.Counter(m.lower() for c in comments for m in c["mentions"])
    topics = collections.Counter(c["topic"] for c in comments if c.get("topic"))
    dated = sorted(k for k in days)
    pct = (lambda k: round(100.0 * k / n, 1)) if n else (lambda k: 0.0)
    total_likes = sum(c.get("likes", 0) for c in comments)
    return {
        "count": n,
        "comments": sum(1 for c in comments if c["type"] == "comment"),
        "replies": sum(1 for c in comments if c["type"] == "reply"),
        "uniqueAuthors": len({c.get("authorName") for c in comments if c.get("authorName")}),
        "totalLikes": total_likes,
        "avgLikes": round(total_likes / n, 2) if n else 0,
        "avgWords": round(sum(c["words"] for c in comments) / n, 1) if n else 0,
        "questions": sum(1 for c in comments if c["isQuestion"]),
        "withEmoji": sum(1 for c in comments if c["emojis"]),
        "sentiment": {k: sent.get(k, 0) for k in LABELS},
        "sentimentPct": {k: pct(sent.get(k, 0)) for k in LABELS},
        "netSentiment": pct(sent.get("positive", 0)) - pct(sent.get("negative", 0)),
        "agentLabeled": sum(1 for c in comments if c.get("sentimentSource") == "agent"),
        "dateRange": {"from": dated[0], "to": dated[-1]} if dated else None,
        "byDay": dict(sorted(days.items())),
        "byHour": {str(h): hours.get(h, 0) for h in range(24)},
        "byWeekday": dict(weekdays.most_common()),
        "peakDay": days.most_common(1)[0] if days else None,
        "peakHour": hours.most_common(1)[0][0] if hours else None,
        "topAuthors": authors.most_common(top),
        "topWords": words.most_common(top * 2),
        "topEmojis": emojis.most_common(top),
        "topHashtags": hashtags.most_common(top),
        "topMentions": mentions.most_common(top),
        "topics": topics.most_common(),
        "topLiked": [brief(c) for c in sorted(comments, key=lambda c: -c.get("likes", 0))[:top]
                     if c.get("likes", 0) > 0],
        "mostNegative": [brief(c) for c in sorted(comments, key=lambda c: c["sentimentScore"])[:top]
                         if c["sentiment"] == "negative"],
        "mostPositive": [brief(c) for c in sorted(comments, key=lambda c: -c["sentimentScore"])[:top]
                         if c["sentiment"] == "positive"],
    }


def group(comments, key, top):
    out = {}
    for k in sorted({c.get(key) or "unknown" for c in comments}):
        sub = [c for c in comments if (c.get(key) or "unknown") == k]
        s = stats(sub, min(top, 5))
        out[k] = {f: s[f] for f in ("count", "replies", "uniqueAuthors", "totalLikes", "sentiment",
                                    "sentimentPct", "netSentiment", "dateRange", "topWords", "topLiked")}
    return out


def digest(comments, size):
    """Most informative comments first: liked, negative, questions, then the rest."""
    def rank(c):
        return (-(c.get("likes", 0)), c["sentimentScore"] >= 0, not c["isQuestion"])
    picked = sorted(comments, key=rank)
    return [brief(c, 400) for c in picked[:size]]


def md_summary(res):
    s = res["overall"]
    lines = ["## Comments analysis", "",
             "- Comments: **%d** (%d top-level, %d replies) from %d authors" % (
                 s["count"], s["comments"], s["replies"], s["uniqueAuthors"]),
             "- Sentiment: %s%% positive · %s%% neutral · %s%% negative (net %+.1f)" % (
                 s["sentimentPct"]["positive"], s["sentimentPct"]["neutral"], s["sentimentPct"]["negative"],
                 s["netSentiment"]),
             "- Likes on comments: %d (avg %.2f) · questions: %d" % (s["totalLikes"], s["avgLikes"], s["questions"])]
    if s["dateRange"]:
        lines.append("- Dates: %s → %s · peak day %s (%d)" % (
            s["dateRange"]["from"], s["dateRange"]["to"], s["peakDay"][0], s["peakDay"][1]))
    if len(res["byPlatform"]) > 1:
        lines.append("- Platforms: " + ", ".join("%s %d" % (k, v["count"]) for k, v in res["byPlatform"].items()))
    if s["topWords"]:
        lines.append("- Top words: " + ", ".join(w for w, _ in s["topWords"][:12]))
    if s["topEmojis"]:
        lines.append("- Top emojis: " + " ".join(e for e, _ in s["topEmojis"][:10]))
    if s["topHashtags"]:
        lines.append("- Hashtags: " + ", ".join(h for h, _ in s["topHashtags"][:8]))
    if res.get("focus"):
        f = res["focus"]
        lines.append("- Focus subset: %d comments (%s%% of total), net sentiment %+.1f" % (
            f["count"], round(100.0 * f["count"] / max(s["count"], 1), 1), f["netSentiment"]))
    if res.get("unansweredQuestions") is not None:
        lines.append("- Questions without a team reply: %d" % len(res["unansweredQuestions"]))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", required=True, help="analysis JSON")
    ap.add_argument("--enriched", help="also write comments with computed fields (for export.py)")
    ap.add_argument("--labels", help="agent labels JSON {id: {sentiment, focus, topic}}")
    ap.add_argument("--team", default="", help="comma-separated brand account names/handles")
    ap.add_argument("--focus-name", default="", help="name of the focus criterion, for the report")
    ap.add_argument("--digest", help="write a compact JSONL digest for the agent")
    ap.add_argument("--digest-size", type=int, default=400)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args(argv)

    with open(a.input, encoding="utf-8") as fh:
        data = json.load(fh)
    comments = data.get("comments", data) if isinstance(data, dict) else data
    if not isinstance(comments, list) or not comments:
        print("error: no comments in %s (run normalize.py first)" % a.input, file=sys.stderr)
        return 1
    labels = {}
    if a.labels:
        with open(a.labels, encoding="utf-8") as fh:
            labels = json.load(fh)
        if isinstance(labels, list):  # also accept [{"id":..., "sentiment":...}]
            labels = {str(x.get("id")): x for x in labels if isinstance(x, dict)}
    team = [t for t in a.team.split(",")]
    enrich(comments, labels, team)

    res = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
           "source": a.input, "overall": stats(comments, a.top),
           "byPlatform": group(comments, "platform", a.top),
           "byPost": group(comments, "postUrl", a.top)}
    focus = [c for c in comments if c.get("focus")]
    if focus:
        res["focusName"] = a.focus_name
        res["focus"] = stats(focus, a.top)
    if any(c["isTeam"] for c in comments):
        res["team"] = [t.strip() for t in team if t.strip()]
        res["unansweredQuestions"] = [brief(c) for c in comments
                                      if c["isQuestion"] and not c["isTeam"] and not c["answeredByTeam"]
                                      and c["type"] == "comment"]
    with open(a.output, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)
    if a.enriched:
        with open(a.enriched, "w", encoding="utf-8") as fh:
            json.dump({"schema": "social-comments/v1+enriched", "count": len(comments), "comments": comments},
                      fh, ensure_ascii=False, indent=1)
    if a.digest:
        with open(a.digest, "w", encoding="utf-8") as fh:
            for row in digest(comments, a.digest_size):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(md_summary(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

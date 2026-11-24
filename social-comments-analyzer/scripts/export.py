#!/usr/bin/env python3
"""Export analyzed comments to CSV, Excel (.xlsx), JSON, Markdown and a
self-contained HTML report (no scripts, no external assets, prints to PDF).

Usage:
  export.py enriched.json --analysis analysis.json --formats html,xlsx,csv,md,json
            --out-dir report/ [--name comments] [--lang en|es] [--title "..."]
            [--summary summary.md] [--focus-only]

  enriched.json   written by analyze.py --enriched
  --summary       Markdown written by the agent (executive summary, findings,
                  recommendations); it goes at the top of the HTML/MD report.
  --focus-only    export only comments the agent marked with focus=true.

Standard library only, no network. Writes only inside --out-dir.
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import zipfile

T = {
    "en": {"title": "Comments report", "generated": "Generated", "summary": "Summary", "kpis": "Key figures",
           "comments": "Comments", "replies": "Replies", "authors": "Authors", "likes": "Likes",
           "questions": "Questions", "sentiment": "Sentiment", "positive": "Positive", "neutral": "Neutral",
           "negative": "Negative", "net": "Net sentiment", "activity": "Activity by day", "hours": "Activity by hour",
           "topAuthors": "Most active authors", "topWords": "Top words", "emojis": "Emojis", "hashtags": "Hashtags",
           "mentions": "Mentions", "platforms": "By platform", "posts": "By post", "post": "Post",
           "platform": "Platform", "topLiked": "Most liked comments", "mostNeg": "Most negative comments",
           "mostPos": "Most positive comments", "unanswered": "Questions without a team reply",
           "focus": "Focus", "topics": "Topics", "share": "share", "range": "Dates", "method":
           "Sentiment is estimated with a multilingual lexicon (Spanish, English, Portuguese) and refined by the "
           "AI agent where labelled; treat it as indicative.", "none": "None"},
    "es": {"title": "Informe de comentarios", "generated": "Generado", "summary": "Resumen", "kpis": "Cifras clave",
           "comments": "Comentarios", "replies": "Respuestas", "authors": "Autores", "likes": "Me gusta",
           "questions": "Preguntas", "sentiment": "Sentimiento", "positive": "Positivo", "neutral": "Neutral",
           "negative": "Negativo", "net": "Sentimiento neto", "activity": "Actividad por día",
           "hours": "Actividad por hora", "topAuthors": "Autores más activos", "topWords": "Palabras más usadas",
           "emojis": "Emojis", "hashtags": "Hashtags", "mentions": "Menciones", "platforms": "Por red social",
           "posts": "Por publicación", "post": "Publicación", "platform": "Red", "topLiked": "Comentarios con más me gusta",
           "mostNeg": "Comentarios más negativos", "mostPos": "Comentarios más positivos",
           "unanswered": "Preguntas sin respuesta del equipo", "focus": "Enfoque", "topics": "Temas",
           "share": "del total", "range": "Fechas", "method":
           "El sentimiento se estima con un diccionario multilingüe (español, inglés, portugués) y lo corrige el "
           "agente de IA donde lo etiquetó; es orientativo.", "none": "Ninguno"},
}

COLUMNS = [  # (key, en, es)
    ("platform", "Platform", "Red"), ("postUrl", "Post", "Publicación"), ("id", "ID", "ID"),
    ("parentId", "Parent ID", "ID padre"), ("type", "Type", "Tipo"), ("replyTo", "Reply to", "Responde a"),
    ("authorName", "Author", "Autor"), ("authorId", "Author ID", "ID autor"), ("authorUrl", "Author URL", "Perfil autor"),
    ("createdAt", "Date (UTC)", "Fecha (UTC)"), ("text", "Comment", "Comentario"), ("likes", "Likes", "Me gusta"),
    ("repliesCount", "Replies", "Respuestas"), ("sentiment", "Sentiment", "Sentimiento"),
    ("sentimentScore", "Sentiment score", "Puntuación"), ("focus", "Focus", "Enfoque"), ("topic", "Topic", "Tema"),
    ("isQuestion", "Question", "Pregunta"), ("isTeam", "Team", "Equipo"), ("hashtags", "Hashtags", "Hashtags"),
    ("mentions", "Mentions", "Menciones"), ("emojis", "Emojis", "Emojis"), ("permalink", "Link", "Enlace"),
]


VALUES_ES = {"comment": "comentario", "reply": "respuesta", "positive": "positivo", "negative": "negativo",
             "neutral": "neutral"}


def cell(v, lang):
    if isinstance(v, bool):
        return ("yes" if v else "") if lang == "en" else ("sí" if v else "")
    if isinstance(v, list):
        return " ".join(str(x) for x in v)
    return "" if v is None else v


def rows(comments, lang):
    i = 1 if lang == "en" else 2
    head = [c[i] for c in COLUMNS]
    tr = VALUES_ES if lang == "es" else {}
    return head, [[tr.get(v, v) if k in ("type", "sentiment") else v
                   for k, v in ((k, cell(c.get(k), lang)) for k, *_ in COLUMNS)] for c in comments]


def safe_formula(v):
    """Neutralize spreadsheet formula injection in text cells."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and not re.fullmatch(r"-?\d+(\.\d+)?", v):
        return "'" + v
    return v


def write_csv(path, comments, lang):
    head, body = rows(comments, lang)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for r in body:
            w.writerow([safe_formula(v) for v in r])


# --- minimal XLSX writer (inline strings) ------------------------------------
def col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


XML_BAD = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def sheet_xml(table):
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/>'
           '</sheetView></sheetViews><sheetData>']
    for r, row in enumerate(table, 1):
        out.append('<row r="%d">' % r)
        for c, v in enumerate(row):
            ref = "%s%d" % (col_name(c), r)
            style = ' s="1"' if r == 1 else ""
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append('<c r="%s"%s><v>%s</v></c>' % (ref, style, v))
            else:
                t = html.escape(XML_BAD.sub("", str(v))[:32000], quote=False)
                out.append('<c r="%s" t="inlineStr"%s><is><t xml:space="preserve">%s</t></is></c>' % (ref, style, t))
        out.append("</row>")
    out.append('</sheetData><autoFilter ref="A1:%s%d"/></worksheet>' % (col_name(max(len(table[0]) - 1, 0)), len(table)))
    return "".join(out)


def write_xlsx(path, sheets):
    names = [n for n, _ in sheets]
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1) for i in range(len(names)))
          + "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>")
    wb = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
          + "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (html.escape(n[:31]), i + 1, i + 1) for i, n in enumerate(names))
          + "</sheets></workbook>")
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1) for i in range(len(names)))
               + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>' % (len(names) + 1)
               + "</Relationships>")
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
              '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
              '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
              '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
              '<cellXfs count="2"><xf fontId="0"/><xf fontId="1" applyFont="1"/></cellXfs></styleSheet>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/styles.xml", styles)
        for i, (_, table) in enumerate(sheets):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), sheet_xml(table))


def summary_table(an, t):
    s = an["overall"]
    tab = [["Metric" if t is T["en"] else "Métrica", "Value" if t is T["en"] else "Valor"],
           [t["comments"], s["count"]], [t["replies"], s["replies"]], [t["authors"], s["uniqueAuthors"]],
           [t["likes"], s["totalLikes"]], [t["questions"], s["questions"]],
           [t["positive"], s["sentiment"]["positive"]], [t["neutral"], s["sentiment"]["neutral"]],
           [t["negative"], s["sentiment"]["negative"]], [t["net"], s["netSentiment"]]]
    if s.get("dateRange"):
        tab.append([t["range"], "%s → %s" % (s["dateRange"]["from"], s["dateRange"]["to"])])
    for w, n in s["topWords"][:20]:
        tab.append([t["topWords"], "%s (%d)" % (w, n)])
    return tab


# --- Markdown -> HTML (headings, lists, bold, italics, links, paragraphs) -----
def inline_md(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md_to_html(md):
    out, lst = [], None
    for line in md.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        li = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*)", line)
        if lst and not li:
            out.append("</%s>" % lst)
            lst = None
        if m:
            lvl = min(len(m.group(1)) + 1, 4)
            out.append("<h%d>%s</h%d>" % (lvl, inline_md(m.group(2)), lvl))
        elif li:
            kind = "ol" if re.match(r"^\s*\d+\.", line) else "ul"
            if not lst:
                out.append("<%s>" % kind)
                lst = kind
            out.append("<li>%s</li>" % inline_md(li.group(1)))
        elif line.strip():
            out.append("<p>%s</p>" % inline_md(line.strip()))
    if lst:
        out.append("</%s>" % lst)
    return "\n".join(out)


CSS = """:root{--bg:#fff;--fg:#1d1b20;--mut:#5f5b66;--line:#e4e1e8;--card:#f7f5fa;--acc:#6750a4;
--pos:#2e7d32;--neu:#8a8791;--neg:#c62828}
@media (prefers-color-scheme:dark){:root{--bg:#141218;--fg:#e6e0e9;--mut:#aaa4b2;--line:#36323c;--card:#1d1b22;
--acc:#cfbcff;--pos:#81c995;--neu:#9a96a1;--neg:#f2a19a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,
"Segoe UI",Roboto,Arial,sans-serif}main{max-width:980px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 10px;border-bottom:1px solid var(--line);
padding-bottom:6px}h3{font-size:16px;margin:20px 0 8px}.mut{color:var(--mut);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.kpi b{display:block;font-size:22px}.kpi span{color:var(--mut);font-size:13px}
.stack{display:flex;height:16px;border-radius:8px;overflow:hidden;margin:8px 0}
.stack i{display:block}.p{background:var(--pos)}.u{background:var(--neu)}.n{background:var(--neg)}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:6px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--mut);font-weight:600}
td.num,th.num{text-align:right;white-space:nowrap}.bar{height:10px;background:var(--acc);border-radius:5px;
min-width:2px}.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}
.q{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0}
.q .m{color:var(--mut);font-size:12px;margin-top:4px}.tag{display:inline-block;padding:1px 8px;border-radius:9px;
font-size:12px;border:1px solid var(--line)}.tag.positive{color:var(--pos)}.tag.negative{color:var(--neg)}
.chips span{display:inline-block;background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:2px 10px;margin:3px;font-size:13px}a{color:var(--acc);word-break:break-all}
@media print{main{max-width:none}h2{break-after:avoid}.q,tr{break-inside:avoid}}"""


def e(s):
    return html.escape(str(s if s is not None else ""))


def bars(pairs, maxn=None):
    if not pairs:
        return ""
    mx = maxn or max(n for _, n in pairs) or 1
    return "<table>" + "".join(
        '<tr><td>%s</td><td style="width:55%%"><div class="bar" style="width:%.1f%%"></div></td><td class="num">%d</td></tr>'
        % (e(k), 100.0 * n / mx, n) for k, n in pairs) + "</table>"


def sent_stack(s, t):
    p = s["sentimentPct"]
    return ('<div class="stack"><i class="p" style="width:%s%%"></i><i class="u" style="width:%s%%"></i>'
            '<i class="n" style="width:%s%%"></i></div><div class="mut">%s %s%% · %s %s%% · %s %s%% · %s %+.1f</div>'
            % (p["positive"], p["neutral"], p["negative"], t["positive"], p["positive"], t["neutral"], p["neutral"],
               t["negative"], p["negative"], t["net"], s["netSentiment"]))


def quotes(items, t):
    if not items:
        return '<p class="mut">%s</p>' % t["none"]
    out = []
    for c in items:
        meta = " · ".join(x for x in (c.get("platform"), ("%d %s" % (c["likes"], t["likes"].lower())) if c.get("likes") else "",
                                      (c.get("createdAt") or "")[:10]) if x)
        out.append('<div class="q"><b>%s</b> <span class="tag %s">%s</span><div>%s</div><div class="m">%s</div></div>'
                   % (e(c.get("author") or "?"), e(c.get("sentiment")), e(t.get(c.get("sentiment"), "")), e(c.get("text")), e(meta)))
    return "".join(out)


def kpis(s, t):
    items = [(t["comments"], s["count"]), (t["replies"], s["replies"]), (t["authors"], s["uniqueAuthors"]),
             (t["likes"], s["totalLikes"]), (t["questions"], s["questions"]), (t["net"], "%+.1f" % s["netSentiment"])]
    return '<div class="kpis">' + "".join('<div class="kpi"><b>%s</b><span>%s</span></div>' % (e(v), e(k)) for k, v in items) + "</div>"


def section_stats(s, t, title):
    h = ["<h2>%s</h2>" % e(title), kpis(s, t), "<h3>%s</h3>" % t["sentiment"], sent_stack(s, t)]
    if s.get("byDay") and len(s["byDay"]) > 1:
        h += ["<h3>%s</h3>" % t["activity"], bars(list(s["byDay"].items())[-45:])]
    if s.get("topics"):
        h += ["<h3>%s</h3>" % t["topics"], bars(s["topics"][:15])]
    h.append('<div class="cols"><div><h3>%s</h3>%s</div><div><h3>%s</h3>%s</div></div>'
             % (t["topAuthors"], bars(s["topAuthors"][:10]), t["topWords"], bars(s["topWords"][:15])))
    chips = [(t["emojis"], s["topEmojis"]), (t["hashtags"], s["topHashtags"]), (t["mentions"], s["topMentions"])]
    for name, items in chips:
        if items:
            h.append('<h3>%s</h3><div class="chips">%s</div>' % (name, "".join("<span>%s %d</span>" % (e(k), n) for k, n in items)))
    h += ["<h3>%s</h3>" % t["topLiked"], quotes(s["topLiked"][:8], t),
          "<h3>%s</h3>" % t["mostNeg"], quotes(s["mostNegative"][:8], t),
          "<h3>%s</h3>" % t["mostPos"], quotes(s["mostPositive"][:6], t)]
    return "\n".join(h)


def group_table(groups, t, label):
    rows_ = "".join('<tr><td>%s</td><td class="num">%d</td><td class="num">%d</td><td class="num">%s%%</td><td class="num">%s%%</td><td class="num">%+.1f</td></tr>'
                    % (('<a href="%s">%s</a>' % (e(k), e(k))) if k.startswith("http") else e(k), g["count"], g["totalLikes"],
                       g["sentimentPct"]["positive"], g["sentimentPct"]["negative"], g["netSentiment"]) for k, g in groups.items())
    return ('<table><tr><th>%s</th><th class="num">%s</th><th class="num">%s</th><th class="num">%s</th><th class="num">%s</th><th class="num">%s</th></tr>%s</table>'
            % (label, t["comments"], t["likes"], t["positive"], t["negative"], t["net"], rows_))


def write_html(path, an, t, title, summary_md, lang):
    s = an["overall"]
    parts = ['<!doctype html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
             '<title>%s</title><style>%s</style></head><body><main>' % (lang, e(title), CSS),
             "<h1>%s</h1><div class='mut'>%s %s · %s %s</div>" % (
                 e(title), t["generated"], e(an.get("generatedAt", "")[:16].replace("T", " ")), t["range"],
                 e("%s → %s" % (s["dateRange"]["from"], s["dateRange"]["to"]) if s.get("dateRange") else "—"))]
    if summary_md:
        parts += ["<h2>%s</h2>" % t["summary"], md_to_html(summary_md)]
    if an.get("focus"):
        f = an["focus"]
        name = an.get("focusName") or t["focus"]
        parts.append(section_stats(f, t, "%s: %s" % (t["focus"], name)))
        parts.append('<p class="mut">%d / %d (%s%% %s)</p>' % (f["count"], s["count"], round(100.0 * f["count"] / max(s["count"], 1), 1), t["share"]))
    parts.append(section_stats(s, t, t["kpis"]))
    if len(an.get("byPlatform", {})) > 1:
        parts += ["<h2>%s</h2>" % t["platforms"], group_table(an["byPlatform"], t, t["platform"])]
    if len(an.get("byPost", {})) > 1:
        parts += ["<h2>%s</h2>" % t["posts"], group_table(an["byPost"], t, t["post"])]
    if s.get("byHour") and any(s["byHour"].values()):
        parts += ["<h2>%s</h2>" % t["hours"], bars([("%02d:00" % int(h), n) for h, n in s["byHour"].items() if n])]
    if an.get("unansweredQuestions") is not None:
        parts += ["<h2>%s (%d)</h2>" % (t["unanswered"], len(an["unansweredQuestions"])), quotes(an["unansweredQuestions"][:30], t)]
    parts.append('<p class="mut" style="margin-top:40px">%s</p></main></body></html>' % t["method"])
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


def write_md(path, an, t, title, summary_md):
    s = an["overall"]
    L = ["# " + title, ""]
    if summary_md:
        L += ["## " + t["summary"], "", summary_md.strip(), ""]
    L += ["## " + t["kpis"], "", "| | |", "|---|---:|"]
    for k, v in summary_table(an, t)[1:10]:
        L.append("| %s | %s |" % (k, v))
    L += ["", "**%s:** %s" % (t["topWords"], ", ".join(w for w, _ in s["topWords"][:15])), ""]
    for key, label in (("topLiked", t["topLiked"]), ("mostNegative", t["mostNeg"])):
        L += ["## " + label, ""]
        for c in s[key][:8]:
            L.append("- **%s** (%s): %s" % (c["author"] or "?", c["sentiment"], c["text"].replace("\n", " ")))
        L.append("")
    if an.get("unansweredQuestions") is not None:
        L += ["## %s (%d)" % (t["unanswered"], len(an["unansweredQuestions"])), ""]
        L += ["- **%s**: %s" % (c["author"] or "?", c["text"].replace("\n", " ")) for c in an["unansweredQuestions"][:30]]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="enriched comments JSON from analyze.py --enriched")
    ap.add_argument("--analysis", help="analysis JSON from analyze.py (needed for html/md and the xlsx summary)")
    ap.add_argument("--formats", default="html,xlsx,csv", help="any of html,xlsx,csv,json,md")
    ap.add_argument("--out-dir", default="comments-report")
    ap.add_argument("--name", default="comments", help="base file name")
    ap.add_argument("--lang", default="en", choices=sorted(T))
    ap.add_argument("--title")
    ap.add_argument("--summary", help="agent-written Markdown summary to include")
    ap.add_argument("--focus-only", action="store_true")
    a = ap.parse_args(argv)

    with open(a.input, encoding="utf-8") as fh:
        data = json.load(fh)
    comments = data.get("comments", []) if isinstance(data, dict) else data
    if a.focus_only:
        comments = [c for c in comments if c.get("focus")]
    an = None
    if a.analysis:
        with open(a.analysis, encoding="utf-8") as fh:
            an = json.load(fh)
    summary_md = ""
    if a.summary:
        with open(a.summary, encoding="utf-8") as fh:
            summary_md = fh.read()
    t = T[a.lang]
    title = a.title or t["title"]
    name = re.sub(r"[^\w.-]+", "-", a.name).strip("-") or "comments"
    os.makedirs(a.out_dir, exist_ok=True)
    formats = [f.strip().lower() for f in a.formats.split(",") if f.strip()]
    written = []
    for f in formats:
        path = os.path.join(a.out_dir, "%s.%s" % (name, f))
        if f == "csv":
            write_csv(path, comments, a.lang)
        elif f == "xlsx":
            head, body = rows(comments, a.lang)
            sheets = [(t["comments"], [head] + body)]
            if an:
                sheets.append((t["summary"], summary_table(an, t)))
            write_xlsx(path, sheets)
        elif f == "json":
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"exportedAt": dt.datetime.now(dt.timezone.utc).isoformat(), "count": len(comments),
                           "analysis": an, "comments": comments}, fh, ensure_ascii=False, indent=1)
        elif f in ("html", "md"):
            if not an:
                print("error: --analysis is required for %s" % f, file=sys.stderr)
                return 2
            (write_html(path, an, t, title, summary_md, a.lang) if f == "html" else write_md(path, an, t, title, summary_md))
        else:
            print("warning: unknown format %s skipped" % f, file=sys.stderr)
            continue
        written.append(path)
    for p in written:
        print(os.path.abspath(p))
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())

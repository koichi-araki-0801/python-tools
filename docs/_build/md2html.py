# -*- coding: utf-8 -*-
"""Markdown 原稿 → 閲覧用 HTML 集約レンダラ。

docs ビルドの唯一の成果物系統。原稿を
**読者別に 1 プロジェクト = 2 枚**のライトモード HTML へ集約する:

  - `<proj>_手引き.html`（audience=guide、読者=オペレータ/利用者）… 操作手順書
  - `<proj>_設計.html`  （audience=spec、読者=エンジニア）… 設計書 → デプロイ運用手順書 →
    仕様一覧（すべて Markdown。仕様一覧は Markdown テーブル）

振り分けは front-matter `audience: guide|spec` を正とし、無指定は名前推定（「操作手順書」
「利用手引き」→ guide、それ以外 → spec）。見た目の `style:` とは独立。

設計方針:
  - Markdown 解析は `markdown-it-py`、front-matter は `python-frontmatter`。docs 固有の描画
    （見出しシフト + TOC・mermaid フェンス・callout・base64 画像図）だけを自前トークン walker で
    組む（下記 render 節）。依存は `docs/_build/requirements.txt`・オフライン時は同梱
    `python-wheelhouse` から導入する。
  - 画像は `docs/<project>/images/*.png` を base64 data-URI でインライン（1 枚で自己完結）。
  - **ライトモード固定**（`prefers-color-scheme` は使わない）。配色は docs 共通のデザイン
    トークン（ACCENT #1F5C99 / INK #20242C / MUTED #606874 ほか）に固定。
  - Mermaid: `docs/_build/vendor/mermaid.min.js`（git 管理外・オフライン重量物バンドル同梱）を
    HTML へインラインしクライアント描画（ライトテーマ固定・flowchart は直角ステップ）。vendor 未配置
    時は `<pre class="mermaid">` を整形コードとして表示し警告を積む。

各原稿は `<section>` で包み、front-matter `title` を h1、本文 `#`〜`###` を +1 シフト（h2〜h4）して
1 HTML 内の階層衝突を防ぐ。左固定サイドバーに「原稿 > 見出し」の 2 段 TOC を生成する。

`build_all.py` から `build_project()` を 1 プロジェクト 1 回呼ぶ。新規 .ps1/.bat は増やさない。
"""
from __future__ import annotations

import base64
import html
import pathlib
import re

import frontmatter
import yaml
from markdown_it import MarkdownIt

# ── デザイントークン（docs 共通・ライト固定）──
CSS_TOKENS = {
    "accent": "#1F5C99",   # 見出しバー・表ヘッダ・番号バッジ・縦バー
    "ink": "#20242C",      # 本文・見出し文字
    "muted": "#606874",    # サブタイトル・キャプション
    "bg": "#FFFFFF",
    "zebra": "#F5F8FB",    # 表の偶数行
    "hair": "#DCE3EA",     # 細罫線・画像枠
    "card": "#FAFBFC",     # カード地
    "code_bg": "#F4F6F8",  # コード網掛け
    "code_bd": "#C4CCD4",  # コード左罫線
    "rule2": "#CDD5DD",    # 見出し下罫線
    "ng_txt": "#B3403F", "ng_fill": "#FDECEC",   # 警告文字・地（callout-WARN / 画像未取得）
}
# callout-NOTE の中立地 #EFF1F4 は CALLOUT_STYLE["NOTE"] が持つ（トークン化しない）。
# callout の `[!TAG]` → 地色 / 枠色。意味で色を分ける: WARN=赤 / INFO=青(情報) /
# NOTE=中立グレー(補足) / TIP=金。NOTE を中立グレーにするのは INFO と同系色だと判別不能になるため。
CALLOUT_STYLE = {
    "WARN": ("#FDECEC", "#E4A9A9"),
    "INFO": ("#EAF2FB", "#B9D3EE"),
    "NOTE": ("#EFF1F4", "#CDD5DD"),
    "TIP": ("#FFF6E5", "#F0D9A0"),
}
CALLOUT_DEFAULT = "INFO"

JP = '"BIZ UDPGothic", "Yu Gothic UI", sans-serif'
MONO = '"BIZ UDGothic", "Consolas", monospace'

VENDOR_MERMAID = pathlib.Path(__file__).resolve().parent / "vendor" / "mermaid.min.js"
# ELK レイアウトエンジン（`@mermaid-js/layout-elk` を単一 IIFE へ自前バンドルしたもの。
# global `mermaidLayoutElk` = レイアウト loader 配列）。未配置なら dagre + step へフォールバック。
VENDOR_ELK = pathlib.Path(__file__).resolve().parent / "vendor" / "mermaid-layout-elk.min.js"

# 読者別の冊子定義: (audience キー, 出力名サフィックス, 冊子タイトルサフィックス)。
BOOKS = (("guide", "手引き"), ("spec", "設計"))

# 冊子内の連結順（ファイル名キーワード → 優先度）。小さいほど先。既定 40。
# spec 冊子は 設計書 → デプロイ運用手順書 → 仕様一覧 の導線になる（設計正典は _build_spec_book で
# 除外。CLAUDE.md へ @import される正典のためファイルは残す）。
_ORDER = [("操作手順書", 10), ("利用手引き", 10), ("設計正典", 15), ("設計書", 20),
          ("デプロイ運用手順書", 30), ("仕様一覧", 50)]


# ── front-matter / インライン ──
def parse_frontmatter(text: str, src_name: str = ""):
    """先頭 `---` ブロックを front-matter として解釈し、`(meta, body)` を返す。

    PyYAML ベースの `python-frontmatter` で読む。改訂履歴 `rev` は原稿側で YAML の
    ブロックシーケンス（`rev:` + `- 版 | 日付 | 内容`）として書き、複数版を list で受ける。
    YAML が壊れていれば失敗のまま止める（黙って冊子を出さない）が、複数原稿を束ねる
    ビルドではどの原稿かが分からないと直せないので、ファイル名を付けて投げ直す。
    """
    try:
        post = frontmatter.loads(text)
    except yaml.YAMLError as e:
        raise ValueError(f"{src_name}: front-matter の YAML が不正です: {e}") from e
    return dict(post.metadata), post.content


def audience_of(src: pathlib.Path, meta: dict | None) -> str:
    """原稿の読者区分を返す（'guide' | 'spec'）。front-matter `audience` 優先、無指定は名前推定。"""
    # YAML は `yes` / `on` を bool にする。文字列以外は指定なしと同じ扱いで名前推定へ倒す。
    raw = (meta or {}).get("audience")
    aud = raw.strip().lower() if isinstance(raw, str) else ""
    if aud in ("guide", "spec"):
        return aud
    return "guide" if ("操作手順書" in src.name or "利用手引き" in src.name) else "spec"


def esc(s: str) -> str:
    """要素の**内容**へ埋める文字列のエスケープ。属性値には使わない(`esc_attr` を使う)。"""
    return html.escape(str(s), quote=False)


def esc_attr(s: str) -> str:
    """属性値へ埋める文字列のエスケープ。引用符も落とす。

    `esc` は `quote=False` なので二重引用符を通す。`alt="{esc(...)}"` のように属性文脈へ
    使うと、原稿の 1 行で属性を閉じて `onerror=` を持ち込める。生成器は
    `MarkdownIt(..., {"html": False})` で本文中の生 HTML を禁じているので、属性文脈での
    取りこぼしがその宣言の唯一の穴になる。**属性値はこちらを通す。**
    """
    return html.escape(str(s), quote=True)


def _mermaid_escape(src: str) -> str:
    """Mermaid ソースの HTML 埋込用エスケープ。`-->` を壊さぬよう `>` は素のまま、`&`/`<` のみ変換。"""
    return src.replace("&", "&amp;").replace("<", "&lt;")


def _image_data_uri(img_dir: pathlib.Path, name: str):
    """`img_dir/name` の画像を data-URI 化して返す。無ければ None。"""
    path = img_dir / name
    if not path.exists():
        return None
    ext = path.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "gif": "image/gif", "svg": "image/svg+xml"}.get(ext, "application/octet-stream")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


# ── Markdown レンダリング（markdown-it-py + docs 固有のトークン walker）──
# ブロック解釈（見出し・リスト・表・段落・blockquote・フェンス）は markdown-it-py へ委譲し、docs
# 固有の描画（見出しの階層シフト + id/TOC・mermaid フェンス・callout・base64 画像図）だけを自前で
# 組む。`html:False` で本文へ生 HTML は通さない。インラインは `emphasis`/`backticks`/`escape` の
# 規則を**無効化**し、`` `code` `` と `**bold**` の 2 種だけを素朴な自前 `inline_html` で処理する。
# 理由: (1) CommonMark の強調 flanking は CJK 句読点隣接の `**「x」**` を bold 化せず literal `**`
# が残る、(2) escape 規則はコード span 内の Windows パス `` `C:\Users\<name>` `` の `\<` を食う。
# 原稿は素の Markdown リンク `[..](..)` や `*em*` を使わず、画像はすべて `![..]`。
_MD = MarkdownIt("commonmark", {"html": False}).enable("table").disable(
    ["emphasis", "backticks", "escape"])
_INLINE_RE = re.compile(r"`([^`]+)`|\*\*([^*]+?)\*\*")


_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _strip_comments(body: str) -> str:
    """コードフェンス外の HTML コメント（`<!-- … -->`）を出力から除く。

    フェンスは ``` と ~~~ の両方を検出し、フェンス内（コード例に現れる `<!-- -->`）は保持
    する。フェンス外は行頭に限らず**行中**のコメントも対象で、複数行にまたがるコメントも
    1 つとして除去する（フェンス外の連続行をまとめて正規表現に掛けるため）。**閉じていない
    コメント**（対応する `-->` が見つからない）は除去しない — `<!--` 以降はそのまま本文として
    残り、後段のインライン処理でエスケープされ読者にリテラル表示される。
    """
    lines = body.split("\n")
    out: list[str] = []
    buf: list[str] = []
    infence = False
    fence_marker = ""

    def flush_buf():
        if buf:
            out.append(_COMMENT_RE.sub("", "\n".join(buf)))
            buf.clear()

    for line in lines:
        s = line.strip()
        if not infence and (s.startswith("```") or s.startswith("~~~")):
            flush_buf()
            infence, fence_marker = True, s[:3]
            out.append(line)
            continue
        if infence and s.startswith(fence_marker):
            infence = False
            out.append(line)
            continue
        if infence:
            out.append(line)
        else:
            buf.append(line)
    flush_buf()
    return "\n".join(out)


def inline_html(text: str) -> str:
    """text ノードのインライン装飾。`` `code` `` と `**bold**` のみ対応（他は HTML エスケープ）。"""
    out, pos = [], 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append(esc(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(f"<code>{esc(m.group(1))}</code>")
        else:
            out.append(f"<strong>{esc(m.group(2))}</strong>")
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)

# markdown-it のブロック開閉トークン → HTML タグ（リスト・表はそのまま素の要素へ）。
_BLOCK_OPEN = {"bullet_list_open": "<ul>",
               "list_item_open": "<li>", "table_open": "<table>", "thead_open": "<thead>",
               "tbody_open": "<tbody>", "tr_open": "<tr>"}
_BLOCK_CLOSE = {"bullet_list_close": "</ul>", "ordered_list_close": "</ol>",
                "list_item_close": "</li>", "table_close": "</table>", "thead_close": "</thead>",
                "tbody_close": "</tbody>", "tr_close": "</tr>", "th_close": "</th>",
                "td_close": "</td>"}


def _render_inline(children, env) -> str:
    """インライン子トークン列 → HTML。emphasis/backticks 無効のため現れるのは text/softbreak/image。

    画像を含まない通常インラインは「全体を空白連結 → `inline_html`」で処理する。段落全体を
    空白連結してから装飾を当てることで、`**bold**` が軟改行をまたぐ場合も 1 度で拾う。
    """
    children = children or []
    if not any(c.type == "image" for c in children):
        text = "".join(" " if c.type in ("softbreak", "hardbreak") else c.content
                       for c in children if c.type in ("text", "softbreak", "hardbreak"))
        return inline_html(text)
    # 画像混在（稀）: トークン毎に処理し、画像は base64 図として差し込む
    out = []
    for t in children:
        if t.type == "text":
            out.append(inline_html(t.content))
        elif t.type in ("softbreak", "hardbreak"):
            out.append(" ")
        elif t.type == "image":
            out.append(_img_html(t, env))
        else:
            out.append(esc(t.content or ""))
    return "".join(out)


def _inline_text(inline_token) -> str:
    """インライントークンの素テキスト（TOC 見出し用。`code`/**bold** マーカーはそのまま残す）。"""
    return "".join(c.content for c in (inline_token.children or [])
                   if c.type == "text")


def _img_html(tok, env) -> str:
    """image トークン → base64 data-URI の `<img>`。未取得は警告 + プレースホルダ。"""
    name = pathlib.Path(tok.attrs.get("src", "")).name
    cap = tok.content or ""
    uri = _image_data_uri(env["img_dir"], name)
    if uri:
        return f'<img alt="{esc_attr(cap)}" src="{uri}">'
    env["warnings"].append(f'{env["src_name"]}: 画像未取得 {name}')
    return f'<div class="img-missing">画像未取得: {esc(name)}</div>'


def _lone_image(inline_token):
    """段落インラインが実質「画像 1 個のみ」なら image トークンを返す。違えば None。"""
    children = inline_token.children or []
    imgs = [c for c in children if c.type == "image"]
    extra = [c for c in children if c.type not in ("image", "softbreak")
             and not (c.type == "text" and not c.content.strip())]
    return imgs[0] if (len(imgs) == 1 and not extra) else None


def _callout_html(tokens, start, end, env) -> str:
    """blockquote 範囲 → callout div。先頭 `[!TAG]` で種別、無ければ INFO（バッジ無し）。"""
    inlines = [t for t in tokens[start:end] if t.type == "inline"]
    tag = None
    if inlines:
        for c in inlines[0].children or []:
            if c.type == "text":
                m = re.match(r"\s*\[!([A-Z]+)\]\s*", c.content)
                if m:
                    tag = m.group(1)
                    c.content = c.content[m.end():]  # マーカーを本文から除く
                break
            if c.type != "softbreak":
                break
    bodies = [_render_inline(t.children, env).strip() for t in inlines]
    body = " ".join(b for b in bodies if b)
    tagkey = tag if tag in CALLOUT_STYLE else CALLOUT_DEFAULT
    badge = f'<span class="callout-tag">{esc(tagkey)}</span>' if tag else ""
    return f'<div class="callout callout-{tagkey}">{badge}{body}</div>'


def _fence_html(tok) -> str:
    """fence トークン → mermaid 専用ブロック or lang ラベル付きコード枠。"""
    lang = (tok.info or "").strip()
    src = tok.content[:-1] if tok.content.endswith("\n") else tok.content
    if lang.lower() == "mermaid":
        return f'<pre class="mermaid">{_mermaid_escape(src)}</pre>'
    label = f'<span class="code-lang">{esc(lang)}</span>' if lang else ""
    return f'<div class="code">{label}<pre><code>{esc(src)}</code></pre></div>'


def render_markdown(body: str, doc_idx: int, img_dir: pathlib.Path, warnings, src_name: str,
                    shift: int = 1):
    """Markdown 本文 → (html 断片, toc エントリ list)。

    見出しは `shift` 段シフトして id を付与する（既定 +1: `#`→h2）。spec 冊子の従文書
    （設計正典・デプロイ運用手順書）は +2 で章見出し h2 の下へ格納する。h4 で頭打ち。
    toc エントリは (nav 階層 1..3, id, テキスト)。解析は markdown-it-py に委譲する。
    """
    env = {"doc_idx": doc_idx, "shift": shift, "img_dir": img_dir,
           "warnings": warnings, "src_name": src_name, "hseq": 0, "toc": []}
    tokens = _MD.parse(_strip_comments(body))  # HTML コメントは出力しない（フェンス内は保持）
    parts = []
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        tt = tok.type
        if tt == "heading_open":
            level = min(int(tok.tag[1:]), 3)
            tag = min(level + shift, 4)
            env["hseq"] += 1
            hid = f'd{doc_idx}-h{env["hseq"]}'
            inline = tokens[i + 1]
            parts.append(f'<h{tag} id="{hid}">{_render_inline(inline.children, env)}</h{tag}>')
            env["toc"].append((min(tag - 1, 3), hid, _inline_text(inline)))
            i += 3  # heading_open, inline, heading_close
        elif tt == "paragraph_open":
            inline = tokens[i + 1]
            if tok.hidden:  # tight list 内の段落はタグを出さず中身だけ
                parts.append(_render_inline(inline.children, env))
            else:
                img = _lone_image(inline)
                if img is not None:
                    inner = _img_html(img, env)
                    cap = img.content or ""
                    caphtml = (f"<figcaption>{esc(cap)}</figcaption>"
                               if cap and inner.startswith("<img") else "")
                    parts.append(f"<figure>{inner}{caphtml}</figure>"
                                 if inner.startswith("<img") else inner)
                else:
                    parts.append(f"<p>{_render_inline(inline.children, env)}</p>")
            i += 3  # paragraph_open, inline, paragraph_close
        elif tt == "blockquote_open":
            depth, j = 1, i + 1
            while j < n and depth:
                if tokens[j].type == "blockquote_open":
                    depth += 1
                elif tokens[j].type == "blockquote_close":
                    depth -= 1
                j += 1
            parts.append(_callout_html(tokens, i + 1, j - 1, env))
            i = j
        elif tt == "fence":
            parts.append(_fence_html(tok))
            i += 1
        elif tt == "inline":
            parts.append(_render_inline(tok.children, env))
            i += 1
        elif tt == "hr":
            parts.append("<hr>")
            i += 1
        elif tt == "ordered_list_open":
            # 画像等で分割された後続リストの連番を保つ（spec のネイティブ採番。guide は CSS
            # カウンタが start を無視するため不変）。
            start = tok.attrs.get("start")
            parts.append(f'<ol start="{start}">' if start else "<ol>")
            i += 1
        elif tt in ("th_open", "td_open"):
            # 表の列整列は markdown-it が区切り行 `:--:` から text-align の style を付ける。
            # それを引き継ぐ（仕様一覧の中央寄せ列を復元。整列指定の無い表は素タグのまま）。
            style = tok.attrGet("style")
            cell = "th" if tt == "th_open" else "td"
            parts.append(f'<{cell} style="{style}">' if style else f"<{cell}>")
            i += 1
        elif tt in _BLOCK_OPEN:
            parts.append(_BLOCK_OPEN[tt])
            i += 1
        elif tt in _BLOCK_CLOSE:
            parts.append(_BLOCK_CLOSE[tt])
            i += 1
        else:
            i += 1  # 未対応トークンは無視（html:False では html_block 等は現れない）

    return "".join(parts), env["toc"]


def _css() -> str:
    t = CSS_TOKENS
    return f"""
:root {{
  --accent:{t['accent']}; --ink:{t['ink']}; --muted:{t['muted']}; --bg:{t['bg']};
  --zebra:{t['zebra']}; --hair:{t['hair']}; --card:{t['card']};
  --code-bg:{t['code_bg']}; --code-bd:{t['code_bd']}; --rule2:{t['rule2']};
}}
* {{ box-sizing:border-box; }}
html {{ scroll-behavior:smooth; }}
html,body {{ margin:0; background:var(--bg); color:var(--ink);
  font-family:{JP}; font-size:15px; line-height:1.75;
  /* 日本語の禁則を厳格化し、長い識別子は語中で折り返してはみ出しを防ぐ */
  line-break:strict; overflow-wrap:break-word; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
code, pre {{ font-family:{MONO}; }}
.layout {{ display:flex; align-items:flex-start; }}
/* 左固定 TOC */
nav.toc {{ position:sticky; top:0; align-self:flex-start; width:290px; min-width:290px;
  height:100vh; overflow-y:auto; padding:22px 16px; border-right:1px solid var(--hair);
  background:var(--card); font-size:13px; }}
nav.toc .doc {{ font-weight:700; color:var(--accent); margin:14px 0 4px;
  border-left:4px solid var(--accent); padding-left:8px; }}
nav.toc a {{ display:block; color:var(--muted); padding:2px 0 2px 6px; }}
nav.toc a.h1 {{ padding-left:10px; color:var(--ink); font-weight:600; }}
nav.toc a.h2 {{ padding-left:22px; }}
nav.toc a.h3 {{ padding-left:34px; font-size:12px; }}
main {{ flex:1; min-width:0; max-width:1000px; padding:28px 44px 120px; }}
section.doc {{ margin-bottom:56px; }}
section.doc + section.doc {{ border-top:2px solid var(--hair); padding-top:28px; }}
section.chapter {{ margin-bottom:44px; }}
h1 {{ font-size:30px; border-left:8px solid var(--accent); padding-left:16px;
  margin:12px 0 8px; letter-spacing:.01em; }}
.subtitle {{ color:var(--muted); font-size:15px; margin:0 0 8px; }}
/* 版チップ + 最終改訂日のメタ行。下に締め罫を入れて扉(masthead)を本文から分離する */
.docmeta {{ display:flex; gap:10px; align-items:center; color:var(--muted); font-size:13px;
  margin:2px 0 26px; padding-bottom:16px; border-bottom:2px solid var(--rule2); }}
.docmeta .ver {{ font-family:{MONO}; font-size:12px; font-weight:700; color:var(--accent);
  background:var(--card); border:1px solid var(--hair); border-radius:4px; padding:0 8px; }}
/* 設計正典章の役割リード（規範の要約であることの宣言） */
h2 {{ font-size:23px; margin:40px 0 12px; padding-bottom:6px; border-bottom:2px solid var(--rule2); }}
h3 {{ font-size:18.5px; margin:24px 0 8px; color:var(--accent); }}
/* h4 は本文(15px)と紛れやすいので太字 + アクセントの短い縦棒で段を明示する */
h4 {{ font-size:16px; font-weight:700; margin:20px 0 6px;
  border-left:3px solid var(--accent); padding-left:8px; }}
h1, h2, h3, h4 {{ scroll-margin-top:10px; line-height:1.4; }}
:focus-visible {{ outline:2px solid var(--accent); outline-offset:2px; border-radius:2px; }}
/* 本文の行長を読める長さ (約 50 字) に抑える。表・図・コードは全幅のまま */
p, ul, ol, .callout {{ max-width:52em; }}
p, li {{ text-wrap:pretty; }}
p {{ margin:10px 0; }}
/* 地の文に混じるコードはチップで目立たせる。表セルは列まるごとコードのことが多く、チップだと
   灰色ピルの塊になって過密なので、セル内は枠・地なしのプレーン等幅にする（識別子は語中で割らない）。 */
p code, li code {{ background:var(--code-bg); border:1px solid var(--hair);
  border-radius:3px; padding:0 4px; font-size:0.92em; overflow-wrap:anywhere; }}
td code {{ font-family:{MONO}; font-size:0.92em; color:var(--ink);
  word-break:keep-all; overflow-wrap:normal; }}
ul, ol {{ margin:8px 0; padding-left:26px; }}
li {{ margin:3px 0; }}
/* コード */
.code {{ position:relative; margin:14px 0; }}
.code pre {{ background:var(--code-bg); border-left:4px solid var(--accent);
  border-radius:0 4px 4px 0; padding:12px 14px; overflow-x:auto; margin:0; font-size:13px;
  line-height:1.6; }}
.code-lang {{ position:absolute; top:0; right:0; background:var(--accent); color:#fff;
  font-size:11px; padding:1px 8px; border-radius:0 4px 0 6px; font-family:{MONO}; }}
/* テーブル。chrome を減らすため四辺罫線は引かず横罫のみ + ゼブラ + ネイビーヘッダで構成する
   （列追跡は整列とゼブラで足りる。罫線とゼブラの二重掛けは過多）。 */
table {{ border-collapse:collapse; width:100%; margin:14px 0; font-size:13.5px;
  display:block; overflow-x:auto; }}
th, td {{ border:none; border-bottom:1px solid var(--hair); padding:6px 12px;
  text-align:left; vertical-align:top; }}
/* 長い表はヘッダをビューポート上端に貼り付けて見出しを保つ */
thead th {{ position:sticky; top:0; z-index:1; padding-top:8px; padding-bottom:8px;
  background:var(--accent); color:#fff; font-weight:700; white-space:nowrap; }}
/* 行を目で追えるよう偶数行ゼブラを適用 */
tbody tr:nth-child(even) {{ background:var(--zebra); }}
/* 列整列は Markdown 区切り行 `:--:` から walker が td/th へ inline text-align を出す */
/* 画像（図番号は冊子通しの CSS カウンタで自動採番） */
body {{ counter-reset:fig; }}
figure {{ margin:16px 0; text-align:center; counter-increment:fig; }}
figure img {{ max-width:100%; height:auto; border:1px solid var(--hair); border-radius:4px; }}
figcaption {{ color:var(--muted); font-size:12.5px; margin-top:6px; }}
figcaption::before {{ content:"図 " counter(fig) "　"; font-weight:700; }}
.img-missing {{ color:{t['ng_txt']}; background:{t['ng_fill']}; border:1px dashed {t['ng_txt']};
  padding:10px; border-radius:4px; }}
/* callout */
.callout {{ margin:14px 0; padding:10px 14px; border:1px solid; border-radius:5px; }}
.callout-tag {{ display:inline-block; font-weight:700; font-size:11px; color:#fff;
  background:var(--accent); border-radius:3px; padding:0 7px; margin-right:8px;
  vertical-align:1px; }}
.callout-WARN {{ background:{CALLOUT_STYLE['WARN'][0]}; border-color:{CALLOUT_STYLE['WARN'][1]}; }}
.callout-INFO {{ background:{CALLOUT_STYLE['INFO'][0]}; border-color:{CALLOUT_STYLE['INFO'][1]}; }}
.callout-NOTE {{ background:{CALLOUT_STYLE['NOTE'][0]}; border-color:{CALLOUT_STYLE['NOTE'][1]}; }}
.callout-TIP {{ background:{CALLOUT_STYLE['TIP'][0]}; border-color:{CALLOUT_STYLE['TIP'][1]}; }}
.callout-WARN .callout-tag {{ background:{t['ng_txt']}; }}
.callout-NOTE .callout-tag {{ background:var(--muted); }}
.callout-TIP .callout-tag {{ background:#B8860B; }}
/* タグチップ先頭に monochrome 記号（FE0E で絵文字化を抑止。走査性の補助） */
.callout-WARN .callout-tag::before {{ content:"\\26A0\\FE0E\\A0"; }}
.callout-INFO .callout-tag::before {{ content:"\\2139\\FE0E\\A0"; }}
.callout-NOTE .callout-tag::before {{ content:"\\270E\\A0"; }}
.callout-TIP .callout-tag::before {{ content:"\\2605\\A0"; }}
/* mermaid（未描画時は整形コードとして見せる） */
pre.mermaid {{ background:var(--card); border:1px solid var(--hair); border-radius:6px;
  padding:16px; text-align:center; overflow-x:auto; line-height:1.4; }}
/* 手引き冊子の最上位番号手順 = 作業ステップカード（本 docs の署名要素）。
   ネストした番号/箇条書きは通常表示のまま */
.book-guide section.doc > ol {{ list-style:none; padding-left:0; counter-reset:step; }}
.book-guide section.doc > ol > li {{ counter-increment:step; position:relative;
  margin:10px 0; padding:10px 16px 10px 56px; background:var(--card);
  border:1px solid var(--hair); border-radius:6px; }}
.book-guide section.doc > ol > li::before {{ content:counter(step); position:absolute;
  left:15px; top:11px; width:27px; height:27px; border-radius:50%; background:var(--accent);
  color:#fff; font-weight:700; font-size:14px; line-height:27px; text-align:center; }}
.book-guide section.doc > ol > li > ol {{ list-style:decimal; padding-left:24px; }}
/* TOC の現在位置ハイライト（スクロールスパイ。インライン JS が .now を付け外しする） */
nav.toc a.now {{ color:var(--accent); font-weight:700; background:#fff; border-radius:3px; }}
@media (max-width:820px) {{
  /* 縦積み時は align-items:flex-start を打ち消して main を全幅に伸ばす
     （残すと main が max-content 幅へ広がりページ全体が横スクロールする） */
  .layout {{ flex-direction:column; align-items:stretch; }}
  nav.toc {{ position:static; width:100%; min-width:0; height:auto; border-right:none;
    border-bottom:1px solid var(--hair); }}
  main {{ padding:18px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior:auto; }}
}}
@media print {{
  nav.toc {{ display:none; }}
  .layout {{ display:block; }}
  main {{ max-width:none; padding:0; }}
  figure, table, .callout {{ break-inside:avoid; }}
  .code pre {{ white-space:pre-wrap; overflow:visible; }}
  a {{ color:inherit; }}
}}
"""


# HTML パーサの script 終端検出は大小文字非依存（`</SCRIPT>` も終端になる）。`re.sub` で
# `</` に script が続く箇所だけ `<\/` へ変換し、`\\/` は JS 上 `/` と等価なので挙動は不変。
_SCRIPT_CLOSE_RE = re.compile(r"</(?=script)", re.IGNORECASE)


def _mermaid_script(has_mermaid: bool) -> str:
    """vendor の mermaid.min.js があればインラインしライトテーマで初期化。無ければ空。

    インライン時は `</script`（大小文字非依存）を `<\\/script` へ置換する（JS 文字列/正規表現内で
    `\\/` は `/` と等価なので挙動不変のまま、HTML パーサによる script 早期終端を防ぐ。終端検出は
    HTML パーサ自体が大小文字非依存のため `</SCRIPT` 等の表記も塞ぐ必要がある）。

    レイアウトは **ELK**（`layout:'elk'`）を使う。ELK の直交ルーティングは矢印終点の向きが自然で
    不要な直角ジグザグが出ないため。ELK バンドル（`VENDOR_ELK`）を先にインラインして
    `registerLayoutLoaders` で登録する。未配置なら dagre へフォールバックし、その場合のみ
    `curve:'step'`（直角ステップ）で dagre の曲線を直角化する。
    """
    if not has_mermaid or not VENDOR_MERMAID.exists():
        return ""
    js = _SCRIPT_CLOSE_RE.sub("<\\/", VENDOR_MERMAID.read_text(encoding="utf-8"))
    use_elk = VENDOR_ELK.exists()
    if use_elk:
        elk = _SCRIPT_CLOSE_RE.sub("<\\/", VENDOR_ELK.read_text(encoding="utf-8"))
        reg = (f"<script>{elk}</script>\n"
               "<script>if(window.mermaidLayoutElk)"
               "mermaid.registerLayoutLoaders(window.mermaidLayoutElk);</script>\n")
        # ELK は直交ルーティング。折点間は直線で結び角を鋭く保つ。
        layout = "layout:'elk',flowchart:{curve:'linear'},"
    else:
        reg = ""
        layout = "flowchart:{curve:'step'},"  # dagre フォールバック時のみ直角ステップ
    init = (
        "mermaid.initialize({startOnLoad:true,theme:'base',"
        f"{layout}"
        "themeVariables:{primaryColor:'#EAF2FB',primaryBorderColor:'#1F5C99',"
        "primaryTextColor:'#20242C',lineColor:'#606874',secondaryColor:'#F5F8FB',"
        "tertiaryColor:'#FFFFFF',fontFamily:'BIZ UDPGothic,sans-serif'}});"
    )
    return f"<script>{js}</script>\n{reg}<script>{init}</script>"


def _scrollspy_script() -> str:
    """左 TOC の現在位置ハイライト（読者の現在地表示）。自己完結の最小 JS。

    IntersectionObserver で「画面上部 1/4 に入っている見出し」を現在地とみなし、対応する
    TOC リンクへ `.now` を付ける。JS 無効環境では単に何も起きない（閲覧は損なわれない）。
    """
    return (
        "<script>(()=>{"
        "const links=[...document.querySelectorAll('nav.toc a[href^=\"#\"]')];"
        "const map=new Map(links.map(a=>[a.getAttribute('href').slice(1),a]));"
        "const obs=new IntersectionObserver(es=>{for(const e of es){"
        "if(!e.isIntersecting)continue;const a=map.get(e.target.id);if(!a)continue;"
        "links.forEach(x=>x.classList.remove('now'));a.classList.add('now');}},"
        "{rootMargin:'0px 0px -75% 0px'});"
        "document.querySelectorAll('main h1[id],main h2[id],main h3[id],main h4[id],"
        "main section[id]').forEach(el=>obs.observe(el));"
        "})();</script>"
    )


def _order_key(path: pathlib.Path):
    name = path.name
    for kw, pri in _ORDER:
        if kw in name:
            return (pri, name)
    return (40, name)


def discover_srcs(proj_dir: pathlib.Path):
    """`docs/<project>/src/` の原稿（.md）を冊子内の導線順に列挙する。"""
    src = proj_dir / "src"
    if not src.is_dir():
        return []
    srcs = list(src.glob("*.md"))
    return sorted(srcs, key=_order_key)


def _doc_meta_row(version, revs) -> str:
    """版チップ + 最終改訂日のメタ行。rev（`版 | 日付 | 内容`）の末尾要素から日付を取る。"""
    parts = []
    if version:
        parts.append(f'<span class="ver">v{esc(version)}</span>')
    if revs:
        cols = [c.strip() for c in str(revs[-1]).split("|")]
        if len(cols) >= 2 and cols[1]:
            parts.append(f'<span class="revdate">最終改訂 {esc(cols[1])}</span>')
    return f'<p class="docmeta">{"".join(parts)}</p>' if parts else ""


def _page(book_title: str, body_class: str, nav_html: str, main_html: str,
          has_mermaid: bool, out_path: pathlib.Path, warnings) -> pathlib.Path:
    """冊子 1 枚の HTML 全体を組み立てて保存する（guide / spec 共通の外殻）。"""
    doc = (
        "<!doctype html>\n"
        '<html lang="ja"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(book_title)}</title>\n"
        f"<style>{_css()}</style>\n</head><body class=\"{body_class}\">\n"
        '<div class="layout">\n'
        f'<nav class="toc"><div class="doc" style="border:none;color:var(--ink)">'
        f"{esc(book_title)}</div>{nav_html}</nav>\n"
        f"<main>{main_html}</main>\n"
        "</div>\n"
        f"{_mermaid_script(has_mermaid)}\n"
        f"{_scrollspy_script()}\n"
        "</body></html>\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc, encoding="utf-8")
    if has_mermaid and not VENDOR_MERMAID.exists():
        warnings.append(f"{out_path.name}: mermaid 図があるが vendor/mermaid.min.js 未配置"
                        "（整形表示のみ・描画は未有効）")
    return out_path


def _build_guide_book(book_title, srcs, img_dir, out_path, warnings):
    """guide 冊子（操作手順書）。原稿ごとの表紙 h1 + 本文の構成。"""
    sections, nav = [], []
    has_mermaid = False
    for di, (src, meta, body) in enumerate(srcs):
        title = meta.get("title") or src.stem
        if "```mermaid" in body:
            has_mermaid = True
        frag, toc = render_markdown(body, di, img_dir, warnings, src.name)
        sub = f'<p class="subtitle">{esc(meta.get("subtitle"))}</p>' if meta.get("subtitle") else ""
        sections.append(
            f'<section class="doc" id="doc{di}"><h1>{esc(title)}</h1>{sub}'
            f'{_doc_meta_row(meta.get("version"), meta.get("rev"))}{frag}</section>')
        nav.append(f'<div class="doc"><a href="#doc{di}">{esc(title)}</a></div>')
        for lv, hid, text in toc:
            nav.append(f'<a class="h{lv}" href="#{hid}">{esc(text)}</a>')
    return _page(book_title, "book-guide", "".join(nav), "".join(sections),
                 has_mermaid, out_path, warnings)


def _build_spec_book(book_title, srcs, img_dir, out_path, warnings):
    """spec 冊子。**全体を 1 つの設計書として組む**（原稿ごとの表紙は出さない）。

    主文書（設計書.md）の front-matter を冊子ヘッダに使い、従文書は h2 章として溶かす:
    設計書本文 → そのまま各章 / デプロイ運用手順書・仕様一覧 → 後半章。従文書の内部見出しは
    +2 シフト（h4 頭打ち）。

    掲載既定は「`discover_srcs` が拾う `docs/<project>/src/*.md` は全件、既定で冊子に載る」
    （`build_project` 参照）。除外はファイル名に「設計正典」を含むものだけの**部分一致**判定
    （下記 `if`）で、これは CLAUDE.md へ @import される正典のためファイルは残しつつ読者向け
    冊子からだけ外す例外。front-matter による掲載可否の切替（`publish` 等）は持たない —
    社内限定で冊子に載せたくない原稿は `src/` 以外の場所へ置くこと。
    """
    pidx = next((i for i, t in enumerate(srcs) if "設計書" in t[0].name), 0)
    pmeta = srcs[pidx][1]
    sections, nav = [], []
    has_mermaid = False

    # 冊子ヘッダ（主文書のメタ）。h1 は 1 つだけ
    sub = f'<p class="subtitle">{esc(pmeta.get("subtitle"))}</p>' if pmeta.get("subtitle") else ""
    header = (f'<section class="doc" id="top"><h1>{esc(pmeta.get("title") or book_title)}</h1>'
              f'{sub}{_doc_meta_row(pmeta.get("version"), pmeta.get("rev"))}</section>')

    for di, (src, meta, body) in enumerate(srcs):
        if "設計正典" in src.name:
            continue  # 正典は冊子に含めない（@import 用にファイルは残す）
        if "```mermaid" in body:
            has_mermaid = True
        if di == pidx:
            # 主文書は章立てをそのまま h2 として展開（章ヘッダは作らない）
            frag, toc = render_markdown(body, di, img_dir, warnings, src.name, shift=1)
            sections.append(f'<section class="chapter" id="doc{di}">{frag}</section>')
            for lv, hid, text in toc:
                nav.append(f'<a class="h{lv}" href="#{hid}">{esc(text)}</a>')
            continue

        # 従文書（デプロイ運用手順書・仕様一覧）: タイトル由来の h2 章ヘッダの下へ格納
        chap_title = meta.get("title") or src.stem
        frag, toc = render_markdown(body, di, img_dir, warnings, src.name, shift=2)
        hid = f"doc{di}-t"
        sections.append(f'<section class="chapter" id="doc{di}">'
                        f'<h2 id="{hid}">{esc(chap_title)}</h2>{frag}</section>')
        nav.append(f'<a class="h1" href="#{hid}">{esc(chap_title)}</a>')
        for lv, hid2, text in toc:
            nav.append(f'<a class="h{lv}" href="#{hid2}">{esc(text)}</a>')

    return _page(book_title, "book-spec", "".join(nav), header + "".join(sections),
                 has_mermaid, out_path, warnings)


def build_project(proj_dir: pathlib.Path, warnings=None):
    """プロジェクトの原稿を読者別（guide/spec）に 2 冊へ集約する。生成したパスの list を返す。"""
    proj_dir = pathlib.Path(proj_dir)
    warnings = warnings if warnings is not None else []
    img_dir = proj_dir / "images"

    # 原稿を一度だけ読み、audience（front-matter）で振り分ける。
    grouped = {"guide": [], "spec": []}
    for src in discover_srcs(proj_dir):
        text = src.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text, src.name)
        grouped[audience_of(src, meta)].append((src, meta, body))

    built = []
    for aud, suffix in BOOKS:
        srcs = grouped[aud]
        if not srcs:
            continue   # 片群が空のプロジェクトはその冊子を出さない
        out_path = proj_dir / f"{proj_dir.name}_{suffix}.html"
        builder = _build_guide_book if aud == "guide" else _build_spec_book
        built.append(builder(f"{proj_dir.name} {suffix}", srcs, img_dir, out_path, warnings))
    return built

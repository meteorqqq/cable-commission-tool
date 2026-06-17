"""页面共用的小型 UI 渲染工具。

只产出 HTML 字符串，由调用方决定通过 st.html / st.markdown 注入。
"""

from __future__ import annotations

import html as _html


_STATUS_CLS = {
    "已完成": "is-done",
    "部分回款": "is-partial",
    "未回款": "is-unpaid",
    "未发货": "is-undeliv",
    "未发货（已收款）": "is-prepaid",
}


def fmt_money(v) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def split_units(s: str | None) -> list[str]:
    if not s:
        return []
    parts = [p.strip() for p in str(s).split("/")]
    return [p for p in parts if p]


def truncate_units_text(s: str | None, max_n: int = 1, max_chars: int = 22) -> str:
    """合同标题里的开票单位需要截断，保持单行整洁。"""
    units = split_units(s)
    if not units:
        return ""
    head = units[:max_n]
    if len(head[0]) > max_chars:
        head[0] = head[0][:max_chars] + "…"
    extra = len(units) - len(head)
    text = " / ".join(head)
    if extra > 0:
        text += f"  +{extra}"
    return text


def status_badge(status: str) -> str:
    cls = _STATUS_CLS.get(status, "")
    return f'<span class="rc-badge {cls}">{_html.escape(status)}</span>'


def unit_pills(units: list[str], limit: int | None = None) -> str:
    if not units:
        return ""
    show = units if limit is None else units[:limit]
    chips = "".join(
        f'<span class="rc-pill" title="{_html.escape(u)}">{_html.escape(u)}</span>'
        for u in show
    )
    extra = (len(units) - len(show)) if limit is not None else 0
    if extra > 0:
        chips += f'<span class="rc-pill" style="background:#FFF;">+{extra} 家</span>'
    return f'<div class="rc-pills-wrap">{chips}</div>'


def kpi_row(items: list[tuple[str, str, bool]]) -> str:
    """items: list of (label, value, accent)."""
    cells = "".join(
        f'<div class="rc-kpi {"is-accent" if accent else ""}">'
        f'<div class="lbl">{_html.escape(label)}</div>'
        f'<div class="val">{_html.escape(value)}</div></div>'
        for label, value, accent in items
    )
    return f'<div class="rc-kpi-grid">{cells}</div>'


def meta_row(items: list[tuple[str, str]]) -> str:
    if not items:
        return ""
    parts = "".join(
        f'<div><span class="k">{_html.escape(k)}</span>'
        f'<span class="v">{_html.escape(v)}</span></div>'
        for k, v in items if v
    )
    return f'<div class="rc-meta">{parts}</div>'


def section_title(text: str) -> str:
    return f'<div class="rc-section-title">{_html.escape(text)}</div>'


def page_intro(
    title: str,
    subtitle: str = "",
    *,
    eyebrow: str = "",
    meta: list[tuple[str, str]] | None = None,
) -> str:
    eyebrow_html = (
        f'<div class="rc-page-eyebrow">{_html.escape(eyebrow)}</div>'
        if eyebrow else ""
    )
    subtitle_html = (
        f'<p class="rc-page-sub">{_html.escape(subtitle)}</p>'
        if subtitle else ""
    )
    meta_html = ""
    if meta:
        items = "".join(
            f'<div class="rc-page-meta-item">'
            f'<span class="k">{_html.escape(k)}</span>'
            f'<span class="v">{_html.escape(v)}</span>'
            f'</div>'
            for k, v in meta if str(v).strip()
        )
        if items:
            meta_html = f'<div class="rc-page-meta">{items}</div>'
    return (
        '<section class="rc-page-hero">'
        '<div class="rc-page-orbit rc-page-orbit-a" aria-hidden="true"></div>'
        '<div class="rc-page-orbit rc-page-orbit-b" aria-hidden="true"></div>'
        '<div class="rc-page-inner">'
        f'{eyebrow_html}'
        f'<h1 class="rc-page-title">{_html.escape(title)}</h1>'
        f'{subtitle_html}'
        f'{meta_html}'
        '</div></section>'
    )


def panel_intro(title: str, subtitle: str = "") -> str:
    subtitle_html = (
        f'<p class="rc-panel-sub">{_html.escape(subtitle)}</p>'
        if subtitle else ""
    )
    return (
        '<div class="rc-panel-intro">'
        f'<div class="rc-panel-title">{_html.escape(title)}</div>'
        f'{subtitle_html}'
        '</div>'
    )


def empty_state(title: str, body: str) -> str:
    return (
        '<div class="rc-empty-state">'
        '<div class="rc-empty-icon" aria-hidden="true">·</div>'
        f'<div class="rc-empty-title">{_html.escape(title)}</div>'
        f'<div class="rc-empty-body">{_html.escape(body)}</div>'
        '</div>'
    )

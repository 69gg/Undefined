"""arXiv 官方 API 客户端。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import cast

from lxml import etree

from Undefined.arxiv.models import PaperInfo
from Undefined.arxiv.parser import normalize_arxiv_id
from Undefined.skills.http_client import request_with_retry

_ARXIV_API_ENDPOINT = "https://export.arxiv.org/api/query"
_HEADERS = {
    "User-Agent": "Undefined-bot/3.x (https://github.com/69gg/Undefined)",
}
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
_ADVANCED_QUERY_REGEX = re.compile(r"\b(?:all|ti|au|abs|cat|jr|rn):", re.I)


@dataclass(frozen=True)
class SearchResponse:
    items: tuple[PaperInfo, ...]
    total_results: int | None
    start_index: int | None


def _normalize_space(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def _build_abs_url(paper_id: str) -> str:
    return f"https://arxiv.org/abs/{paper_id}"


def _build_pdf_url(paper_id: str) -> str:
    return f"https://arxiv.org/pdf/{paper_id}.pdf"


def _xml_text(node: etree._Element | None, xpath: str) -> str:
    if node is None:
        return ""
    result = node.findtext(xpath, default="", namespaces=_NS)
    return _normalize_space(result)


def _link_url(entry: etree._Element, *, rel: str, title: str | None = None) -> str:
    for link in entry.findall("atom:link", namespaces=_NS):
        rel_value = _normalize_space(link.get("rel"))
        title_value = _normalize_space(link.get("title"))
        if rel_value != rel:
            continue
        if title is not None and title_value != title:
            continue
        href = _normalize_space(link.get("href"))
        if href:
            return href
    return ""


def _parse_entry(entry: etree._Element) -> PaperInfo:
    entry_id = _xml_text(entry, "atom:id")
    paper_id = normalize_arxiv_id(entry_id) or ""
    if not paper_id:
        alternate_url = _link_url(entry, rel="alternate")
        paper_id = normalize_arxiv_id(alternate_url) or ""
    if not paper_id:
        raise ValueError("无法从 arXiv API 结果中解析论文 ID")

    authors = tuple(
        _normalize_space(author.findtext("atom:name", default="", namespaces=_NS))
        for author in entry.findall("atom:author", namespaces=_NS)
        if _normalize_space(author.findtext("atom:name", default="", namespaces=_NS))
    )
    abs_url = _link_url(entry, rel="alternate") or _build_abs_url(paper_id)
    pdf_url = _link_url(entry, rel="related", title="pdf") or _build_pdf_url(paper_id)
    primary_category = ""
    primary_node = entry.find("arxiv:primary_category", namespaces=_NS)
    if primary_node is not None:
        primary_category = _normalize_space(primary_node.get("term"))

    return PaperInfo(
        paper_id=paper_id,
        title=_xml_text(entry, "atom:title"),
        authors=authors,
        summary=_xml_text(entry, "atom:summary"),
        published=_xml_text(entry, "atom:published"),
        updated=_xml_text(entry, "atom:updated"),
        primary_category=primary_category,
        abs_url=abs_url,
        pdf_url=pdf_url,
    )


def _parse_feed(xml_payload: bytes) -> etree._Element:
    try:
        return etree.fromstring(xml_payload)
    except etree.XMLSyntaxError as exc:
        raise ValueError("arXiv API 返回了无法解析的 XML") from exc


def _find_entries(feed: etree._Element) -> Iterable[etree._Element]:
    return cast(list[etree._Element], feed.findall("atom:entry", namespaces=_NS))


async def get_paper_info(
    paper_id: str,
    *,
    context: dict[str, object] | None = None,
) -> PaperInfo:
    normalized = normalize_arxiv_id(paper_id)
    if normalized is None:
        raise ValueError(f"无法解析 arXiv 标识: {paper_id}")

    response = await request_with_retry(
        "GET",
        _ARXIV_API_ENDPOINT,
        params={"id_list": normalized},
        headers=_HEADERS,
        default_timeout=30.0,
        follow_redirects=True,
        context=context,
    )
    feed = _parse_feed(response.content)
    entries = list(_find_entries(feed))
    if not entries:
        raise ValueError(f"未找到 arXiv 论文: {normalized}")
    return _parse_entry(entries[0])


def _build_search_query(query: str) -> str:
    stripped = _normalize_space(query)
    if not stripped:
        raise ValueError("请提供搜索内容。")
    if _ADVANCED_QUERY_REGEX.search(stripped):
        return stripped
    keywords = [part for part in stripped.split(" ") if part]
    return " AND ".join(f"all:{keyword}" for keyword in keywords)


async def search_papers(
    query: str,
    *,
    start: int = 0,
    max_results: int = 5,
    context: dict[str, object] | None = None,
) -> SearchResponse:
    safe_start = max(0, int(start))
    safe_max_results = max(1, min(int(max_results), 20))
    search_query = _build_search_query(query)

    response = await request_with_retry(
        "GET",
        _ARXIV_API_ENDPOINT,
        params={
            "search_query": search_query,
            "start": safe_start,
            "max_results": safe_max_results,
        },
        headers=_HEADERS,
        default_timeout=30.0,
        follow_redirects=True,
        context=context,
    )
    feed = _parse_feed(response.content)
    items = tuple(_parse_entry(entry) for entry in _find_entries(feed))

    total_results_text = _xml_text(feed, "opensearch:totalResults")
    start_index_text = _xml_text(feed, "opensearch:startIndex")
    total_results = int(total_results_text) if total_results_text.isdigit() else None
    start_index = int(start_index_text) if start_index_text.isdigit() else None
    return SearchResponse(
        items=items,
        total_results=total_results,
        start_index=start_index,
    )

import httpx
import pytest
from bs4 import BeautifulSoup

from qfnu_course_web.app import create_app


@pytest.mark.asyncio
async def test_page_has_accessible_operational_structure() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get("/")
    soup = BeautifulSoup(response.text, "html.parser")
    assert "lunar-console" in soup.body.get("class", [])
    assert soup.select_one('#cosmic-backdrop[aria-hidden="true"]')
    assert "月面电波终端" in soup.select_one(".app-header").get_text(" ", strip=True)
    assert len(soup.select("h1")) == 1
    assert soup.select('[aria-live="polite"]')
    assert soup.select("table caption")
    assert soup.select('meta[name="viewport"]')
    assert soup.select_one("#catalog-round")
    assert soup.select_one("#catalog-load")
    assert soup.select_one("#catalog-filter")
    assert soup.select_one("#catalog-module")
    assert soup.select_one("#catalog-statuses")
    assert soup.select_one("#catalog-table")
    assert soup.select_one("#automation-status")
    assert not soup.select_one("#countdown-status")
    assert not soup.select_one("#backoff-status")
    assert soup.select_one("#automation-username")
    assert soup.select_one("#keychain-password")
    assert soup.select_one("#password-save")
    assert soup.select_one("#password-delete")
    assert not soup.select_one("#ocr-url")
    assert "内置 OCR 会随控制台启动" in response.text
    assert soup.select_one("#ocr-attempts")
    assert soup.select_one("#keepalive-seconds")
    assert not soup.select_one("#round-keywords")
    assert not soup.select_one("#start-time")
    assert not soup.select_one("#term-id")
    assert not soup.select_one("#request-rate")
    assert not soup.select_one("#poll-interval")
    assert soup.select_one("#advanced-target-open")
    assert soup.select_one("#target-mode").get("value") == "advanced"
    assert soup.select_one("#target-course-code").has_attr("required")
    assert not soup.select_one("#target-course-id")
    assert not soup.select_one("#target-class-id")
    assert not soup.select_one("#pause")
    assert not soup.select_one("#resume")
    assert not soup.select_one("#config-file")
    assert not soup.select_one('a[href="/api/config/export"]')
    assert not soup.select_one("#max-runtime")
    assert soup.select_one("#automation-captcha-dialog")
    assert not soup.select_one("#target-open")
    catalog_headers = {
        header.get_text(" ", strip=True) for header in soup.select("#catalog-table th")
    }
    assert {"模块", "课程", "教师", "学分", "开课单位 / 类别", "人数", "操作"} <= catalog_headers
    for field in soup.select('input:not([type="hidden"]), select, textarea'):
        assert field.get("id") and soup.select_one(f'label[for="{field["id"]}"]')
    assert all(
        script.get("src", "").startswith("/static/") for script in soup.select("script[src]")
    )

import httpx


def site_cookies(values: dict[str, str]) -> httpx.Cookies:
    """Never forward account cookies to image hosts or external redirects."""
    jar = httpx.Cookies()
    for name, value in values.items():
        for domain in (["exhentai.org"] if name == "igneous" else ["e-hentai.org", "exhentai.org"]):
            jar.set(name, value, domain=domain, path="/")
    return jar

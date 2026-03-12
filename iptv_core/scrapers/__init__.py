"""Scraper registry for sync sources."""
from .acestreamid import scrape as scrape_acestreamid
from .generic import scrape as scrape_generic
from .hashes_json import scrape as scrape_hashes_json
from .new_era import scrape as scrape_new_era
from .vk_article import scrape as scrape_vk_article

SCRAPER_REGISTRY = {
    "new_era": scrape_new_era,
    "acestreamid": scrape_acestreamid,
    "hashes_json": scrape_hashes_json,
    "vk_article": scrape_vk_article,
    "generic": scrape_generic,
}


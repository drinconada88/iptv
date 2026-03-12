"""Scraper registry for sync sources."""
from .acestreamid import scrape as scrape_acestreamid
from .generic import scrape as scrape_generic
from .new_era import scrape as scrape_new_era

SCRAPER_REGISTRY = {
    "new_era": scrape_new_era,
    "acestreamid": scrape_acestreamid,
    "generic": scrape_generic,
}


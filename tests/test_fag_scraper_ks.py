"""Tests for FaGScraperKS and CGRFetcherKS — Phase 6 Slice 6.2."""

from scripts.blackboard.schema import WorkItem
from scripts.knowledge.fag_scraper import CGRFetcherKS, FaGScraperKS


def test_fag_scraper_ks_name():
    ks = FaGScraperKS()
    assert ks.name == "FaGScraperKS"


def test_fag_scraper_eligible_for_its_own_work():
    ks = FaGScraperKS()
    item = WorkItem(work_id="w1", pensioner_id=1, knowledge_source="FaGScraperKS")
    assert ks.eligible(item) is True


def test_fag_scraper_not_eligible_for_other_work():
    ks = FaGScraperKS()
    item = WorkItem(work_id="w1", pensioner_id=1, knowledge_source="OtherKS")
    assert ks.eligible(item) is False


def test_fag_scraper_estimated_cost():
    ks = FaGScraperKS()
    item = WorkItem(work_id="w1", pensioner_id=1, knowledge_source="FaGScraperKS")
    assert ks.estimated_cost(item) == 1

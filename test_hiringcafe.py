"""Standalone smoke test for hiringcafe_service.

Hits the real hiring.cafe API and prints what came back. Run from the terminal:

    python test_hiringcafe.py

It temporarily shrinks config.RESULTS_WANTED so the run is quick and gentle on
the API; remove that line to exercise the full configured limit.
"""

import json

import requests

from config import Config as config
import hiringcafe_service


def print_search_context() -> None:
    """Show the config filters and the exact URL run_scrape() will query.

    Rebuilds the search state with the service's own helpers so what we print is
    byte-for-byte what run_scrape() sends (including the geocoded location and the
    rotating Next.js buildId). Wrapped defensively so a network hiccup here never
    blocks the actual scrape below.
    """
    print("=" * 70)
    print("SEARCH FILTERS (from config)")
    print("=" * 70)
    print(f"  SEARCH_TERM:    {config.SEARCH_TERM!r}")
    print(f"  LOCATION:       {config.LOCATION!r}")
    print(f"  IS_REMOTE:      {config.IS_REMOTE}")
    print(f"  HOURS_OLD:      {config.HOURS_OLD}")
    print(f"  RESULTS_WANTED: {config.RESULTS_WANTED}")

    try:
        session = hiringcafe_service._session()
        build_id = hiringcafe_service._get_build_id(session)
        search_state = hiringcafe_service._build_search_state(session)

        # Human-readable summary of the resolved searchState filters.
        print("\n  Resolved searchState filters sent to hiring.cafe:")
        print(f"    searchQuery:           {search_state.get('searchQuery')!r}")
        print(f"    defaultToUserLocation: {search_state.get('defaultToUserLocation')}")
        locations = search_state.get("locations") or []
        if locations:
            loc = locations[0]
            print(f"    location:              {loc.get('formatted_address')!r}  options={loc.get('options')}")
        else:
            print("    location:              (none — unfiltered)")
        print(f"    workplaceTypes:        {search_state.get('workplaceTypes', '(not set — any)')}")
        print(f"    dateFetchedPastNDays:  {search_state.get('dateFetchedPastNDays', '(not set — any)')}")

        # Exact request URL for page 0 (PreparedRequest matches requests' encoding).
        data_url = f"{hiringcafe_service._BASE}/_next/data/{build_id}/index.json"
        prepared = requests.Request(
            "GET", data_url, params={"searchState": json.dumps(search_state), "page": 0}
        ).prepare()
        print(f"\n  buildId: {build_id}")
        print("\n  Final search URL (page 0):")
        print(f"    {prepared.url}")
    except Exception as e:
        print(f"\n  (could not build search context preview: {e})")

    print("=" * 70)


def main() -> None:
    # Keep the live verification small/fast (the real run uses config.RESULTS_WANTED).
    setattr(config, "RESULTS_WANTED", 50)

    print_search_context()

    jobs, errors = hiringcafe_service.run_scrape()

    print("=" * 70)
    print(f"run_scrape() returned {len(jobs)} jobs and {len(errors)} error(s)")
    print("=" * 70)

    for i, job in enumerate(jobs, 1):
        print(f"\n[{i}] {job.role}  @  {job.company}")
        print(f"    salary: {job.salary}")
        print(f"    link:   {job.link}")
        desc_len = len(job.description) if job.description else 0
        print(f"    description chars: {desc_len}")

    if errors:
        print("\nERRORS:")
        for err in errors:
            print(f"  - {err}")


if __name__ == "__main__":
    main()

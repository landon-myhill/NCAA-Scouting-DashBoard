"""
data — acquisition: scrapers, parsers, and merge steps.

    scrape.py               current-season D1 stats -> players.json
    scrape_history.py       prior seasons -> history/players_<year>.json
    scrape_draft.py         declared draft entrants -> draft_eligible.json
    scrape_draft_results.py NBA draft results + careers -> history/draft_results_*
    scrape_recruits.py      HS recruit rankings -> recruits/recruits_*.json
    parse_recruits.py       recruits/raw/*.tsv -> recruits/recruits_*.json
    parse_combine.py        combine/raw/* -> combine/combine_*.json
    merge_recruits.py       stamp recruit_rank onto every player file
    merge_combine.py        stamp combine measurements onto player files

Run as modules from the repo root, e.g. `python -m data.scrape`,
or run the whole DAG with `python pipeline.py scrape`.
"""

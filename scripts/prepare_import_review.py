#!/usr/bin/env python3
"""Prepare an immutable review bundle; never apply candidates to the source corpus."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from extract_review_candidates import parse_document
from ru_source_updates.transport import official_url


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def checked_timestamp(value, field):
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp or null")
    if field == "official_updated_at" and len(value) == 10:
        datetime.strptime(value, "%Y-%m-%d")
        return
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} needs an explicit timezone")


def source_states(path, raw=None):
    if path is None:
        return {}
    value = json.loads((path.read_bytes() if raw is None else raw).decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError("source state must be an object")
    rows = value.get("sources")
    if not isinstance(rows, list):
        raise ValueError("source state must contain a sources list")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("source_url"), str):
            raise ValueError("source state entries need a source_url")
        url = official_url(row["source_url"])
        if url in result:
            raise ValueError("duplicate source URL in source state")
        for field in ["official_updated_at", "last_source_checked_at", "last_imported_at"]:
            checked_timestamp(row.get(field), field)
        result[url] = row
    return result


def validated_document(path, reference, candidate_raw=None, reference_raw=None):
    candidate = json.loads((path.read_bytes() if candidate_raw is None else candidate_raw).decode('utf-8'))
    if not isinstance(candidate, dict):
        raise ValueError("candidate document must be an object")
    raw = reference.read_bytes() if reference_raw is None else reference_raw
    lines = raw.decode('utf-8').splitlines()
    if not lines:
        raise ValueError(f"empty reference: {reference.name}")
    source_url = candidate.get("source_url")
    if not isinstance(source_url, str) or source_url != lines[0].strip():
        raise ValueError(f"candidate source URL differs: {reference.name}")
    official_url(source_url)
    source_file = candidate.get('source_file')
    if not isinstance(source_file, str) or Path(source_file).resolve() != reference.resolve():
        raise ValueError(f"candidate source path differs: {reference.name}")
    if candidate.get("source_sha256") != digest(raw):
        raise ValueError(f"candidate source hash differs: {reference.name}")
    if candidate.get("extraction_complete") is not True or candidate.get("extraction_errors"):
        raise ValueError(f"incomplete extraction: {reference.name}")
    if candidate.get("publication_ready") is not False:
        raise ValueError("review candidates must explicitly be nonpublishable")
    parties = candidate.get("parties")
    if not isinstance(parties, list) or not parties:
        raise ValueError(f"no source parties to review: {reference.name}")
    for party in parties:
        if not isinstance(party, dict):
            raise ValueError("source parties must be objects")
        proof = party.get("provenance", {})
        if not isinstance(proof, dict):
            raise ValueError("source provenance must be an object")
        start, end = proof.get("line_start"), proof.get("line_end")
        if type(start) is not int or type(end) is not int or not 1 <= start <= end <= len(lines):
            raise ValueError(f"invalid source line span: {reference.name}")
        source_lines = lines[start - 1:end]
        if proof.get("raw_lines") != source_lines:
            raise ValueError(f"candidate source text differs: {reference.name}")
        normalized = " ".join(" ".join(source_lines).split())
        title = party.get('raw_title')
        if not isinstance(title, str) or ' '.join(title.split()) not in normalized:
            raise ValueError(f"title absent from referenced source: {reference.name}")
        names = party.get("names")
        if not isinstance(names, list) or not names:
            raise ValueError("each source party needs a name")
        for name in names:
            if not isinstance(name, dict):
                raise ValueError("source names must be objects")
            text = name.get("raw")
            if not isinstance(text, str) or not text.strip() or " ".join(text.split()) not in normalized:
                raise ValueError(f"name absent from referenced source: {reference.name}")
    # Completeness and metadata cannot be established by candidate self-report.
    # Re-extract the exact frozen bytes and require the complete ordered evidence.
    # Compare the persisted JSON contract: diagnostic tuples become arrays when
    # the extractor writes its candidates, without changing their evidence.
    expected = json.loads(json.dumps(parse_document(reference, raw=raw)))
    unexpected = set(candidate) - set(expected) - {'existing_corpus_comparison'}
    if unexpected:
        raise ValueError(f"unexpected candidate fields: {', '.join(sorted(unexpected))}")
    for key, value in expected.items():
        if key != 'source_file' and candidate.get(key) != value:
            raise ValueError(f"candidate {key} differs from complete source extraction: {reference.name}")
    return candidate


def prepare_review(source_root, candidates_dir, output_dir, state_file=None):
    root = Path(source_root).resolve()
    candidates = Path(candidates_dir).resolve()
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError("output directory must be new; existing bundles are preserved")
    if output.is_relative_to(root) or output.is_relative_to(candidates):
        raise ValueError("output directory must be outside the source and candidate directories")
    references = sorted((root / "reference-docs/announcements").glob("*.md"))
    if not references:
        raise ValueError("no tracked reference announcements found")
    expected = {p.stem + ".review-candidates.json" for p in references}
    actual = {p.name for p in candidates.glob("*.review-candidates.json")}
    if actual != expected:
        raise ValueError("candidate set must cover exactly all tracked references")
    protected = {}

    def snapshot(path):
        data = path.read_bytes()
        protected[path] = data
        return data

    state_path = Path(state_file).resolve() if state_file else None
    state_raw = snapshot(state_path) if state_path else None
    states = source_states(state_path, raw=state_raw)
    inputs = []
    # Freeze bytes before validating any candidate. Copies always use these same
    # bytes, and a final comparison detects changes to live inputs during the run.
    for reference in references:
        candidate_path = candidates / (reference.stem + ".review-candidates.json")
        if not reference.resolve().is_relative_to(root):
            raise ValueError("source reference resolves outside the source root")
        manual = root / "sources/announcements" / (reference.stem + ".yml")
        if manual.is_file() and not manual.resolve().is_relative_to(root):
            raise ValueError("manual data resolves outside the source root")
        inputs.append((reference, candidate_path, manual,
                       snapshot(reference), snapshot(candidate_path),
                       snapshot(manual) if manual.is_file() else None))
    documents = []
    # Validate every document before creating any output. No partial bundle is accepted.
    for reference, candidate_path, manual, reference_raw, candidate_raw, original in inputs:
        candidate = validated_document(candidate_path, reference, candidate_raw, reference_raw)
        state = states.get(official_url(candidate['source_url']), {})
        documents.append((reference, candidate_path, manual, reference_raw, candidate_raw, original, candidate, state))
    output.mkdir(parents=True)
    for name in ["references", "originals", "candidates"]:
        (output / name).mkdir()
    manifest = {
        "schema": "ru-import-review/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "REVIEW_REQUIRED",
        "publication_ready": False,
        "scope": "all_tracked_reference_announcements",
        "source_root": str(root),
        "source_state_file": "source-state.json" if state_raw is not None else None,
        "source_state_sha256": digest(state_raw) if state_raw is not None else None,
        "sources": [],
        "limits": ["No source file, import ledger or published dataset is modified.",
                   "Complete extraction does not resolve source disagreements or approve identities.",
                   "No claim that tracked references cover every current official announcement."]
    }
    if state_raw is not None:
        (output / 'source-state.json').write_bytes(state_raw)
    for reference, candidate_path, manual, reference_raw, candidate_raw, original, candidate, state in documents:
        reference_copy = output / "references" / reference.name
        candidate_copy = output / "candidates" / candidate_path.name
        reference_copy.write_bytes(reference_raw)
        candidate_copy.write_bytes(candidate_raw)
        original_copy = None
        if original is not None:
            original_copy = output / "originals" / manual.name
            original_copy.write_bytes(original)
        manifest["sources"].append({
            "source_url": candidate.get("source_url"),
            "reference": str(reference_copy.relative_to(output)),
            "reference_sha256": digest(reference_raw),
            "original_manual_file": str(original_copy.relative_to(output)) if original_copy else None,
            "original_manual_sha256": digest(original) if original is not None else None,
            "candidate_file": str(candidate_copy.relative_to(output)),
            "candidate_sha256": digest(candidate_raw),
            "candidate_count": len(candidate["parties"]),
            "source_warnings": candidate.get("source_warnings", candidate.get("issues", [])),
            "source_publication_evidence": candidate.get("publication_timestamp_evidence"),
            "source_as_of_evidence": candidate.get("as_of_date_evidence"),
            "official_updated_at": state.get("official_updated_at"),
            "last_source_checked_at": state.get("last_source_checked_at"),
            "last_imported_at": state.get("last_imported_at"),
            "source_check": state if state else None,
            "review_status": "pending"
        })
    if any(not path.is_file() or path.read_bytes() != saved for path, saved in protected.items()):
        raise ValueError("an input changed while preparing the bundle; reject this bundle")
    write_json(output / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--candidates-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()
    try:
        report = prepare_review(args.source_root, args.candidates_dir, args.output_dir, args.state_file)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.exit(2, f"Import review refused: {error}\n")
    print(json.dumps({"sources": len(report["sources"]), "status": report["status"],
                      "publication_ready": report["publication_ready"]}))


if __name__ == "__main__":
    main()

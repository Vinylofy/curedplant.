from scripts.importers import bol_metadata_backfill as subject


def response(ean="0191401214230", title="Alive in the Catacombs", artist="Queens of the Stone Age", media="Vinyl"):
    return {"ean":ean,"title":title,"bolProductId":"9300000385536914","specificationGroups":[
        {"specifications":[{"name":"Artiest(en)","values":[artist]},
                            {"name":"Muziekdrager","values":[media]}]}]}


def product():
    return {"ean":"0191401214230","artist":"Queens Of The Stone Age","title":"Vinyl 0191401214230"}


def test_exact_qotsa_ean_is_normalized_without_touching_identity():
    actual=subject.normalize_response(product(),response())
    assert actual["title"]=="Alive in the Catacombs"
    assert actual["artist"]=="Queens of the Stone Age"


def test_rejects_ean_mismatch_cd_and_technical_title():
    for changed in (response(ean="0191401214231"),response(media="CD"),response(title="Vinyl 0191401214230")):
        try: subject.normalize_response(product(),changed)
        except ValueError: pass
        else: raise AssertionError("unsafe Bol metadata accepted")


def test_existing_artist_is_safe_fallback_when_bol_artist_is_absent():
    value=response(); value["specificationGroups"][0]["specifications"]=value["specificationGroups"][0]["specifications"][1:]
    assert subject.normalize_response(product(),value)["artist"]=="Queens Of The Stone Age"


def test_exact_bol_title_is_accepted_without_an_available_artist():
    value=response(); value["specificationGroups"][0]["specifications"]=value["specificationGroups"][0]["specifications"][1:]
    item=product(); item["artist"]="Unknown artist"
    actual=subject.normalize_response(item,value)
    assert actual["title"]=="Alive in the Catacombs"
    assert actual["artist"] is None


def test_workflow_is_manual_ubuntu_and_bounded():
    from pathlib import Path
    text=Path(".github/workflows/bol-metadata-backfill.yml").read_text()
    assert "workflow_dispatch:" in text and "schedule:" not in text
    assert "runs-on: ubuntu-latest" in text
    assert "LIMIT <= 1500" in text


def test_dict_cursor_total_is_read_by_column_name():
    from pathlib import Path
    text=Path("scripts/importers/bol_metadata_backfill.py").read_text()
    assert '.fetchone()["count"]' in text

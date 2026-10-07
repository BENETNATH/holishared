"""B026 — Média : miniatures, formats, envoi multiple, galerie, visionneuse."""

import io
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from app.extensions import limiter
from app.models import Event, MediaItem


def _dt(*args):
    return datetime(*args)  # noqa: DTZ001 - dates naïves, comme les colonnes


HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1" + b"0" * 32


def _jpeg(
    width=400, height=200, *, orientation=None, gps=False, taken="2024:07:14 10:20:30", color="red"
):
    img = Image.new("RGB", (width, height), color)
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    if gps:
        exif.get_ifd(0x8769)[36867] = taken
        ifd = exif.get_ifd(0x8825)
        ifd[1], ifd[2], ifd[3], ifd[4] = "N", (48.0, 51.0, 24.0), "E", (2.0, 21.0, 7.0)
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _folder(app, event):
    path = Path(app.instance_path) / "media" / event.code
    path.mkdir(parents=True, exist_ok=True)
    return path


def _item(
    app,
    db,
    event,
    data=None,
    *,
    name="p.jpg",
    mime="image/jpeg",
    uploaded_by=None,
    taken=None,
    caption="",
    **kw,
):
    """Média réel : fichier sur disque + ligne en base (aucune miniature : génération paresseuse)."""
    row = MediaItem(
        filename=f"{name.split('.')[0]}-{len(MediaItem.query.all())}.{name.split('.')[-1]}",
        original_name=name,
        mime_type=mime,
        size_bytes=len(data or b"x"),
        caption=caption,
        taken_at=taken,
        uploaded_by=uploaded_by,
        uploaded_by_name="Camille",
        event_id=event.id,
        **kw,
    )
    db.session.add(row)
    db.session.commit()
    (_folder(app, event) / row.filename).write_bytes(data if data is not None else _jpeg())
    return row


def _upload(client, event, data, name="a.jpg", mime="image/jpeg", query="", **form):
    return client.post(
        f"/e/{event.code}/media/upload{query}",
        data={"file": (io.BytesIO(data), name, mime), **form},
        content_type="multipart/form-data",
        headers={"Accept": "application/json"},
    )


def _thumb(client, event, item, size=320):
    return client.get(f"/e/{event.code}/media/{item.id}/thumb/{size}")


# --- 26.1 miniatures ------------------------------------------------------------------------------------------


def test_thumb_first_access_for_existing_media_returns_webp(creator_client, app, db, event):
    item = _item(app, db, event)
    resp = _thumb(creator_client, event, item)
    assert (resp.status_code, resp.mimetype) == (200, "image/webp")


def test_thumb_first_access_writes_cache_file_on_disk(creator_client, app, db, event):
    item = _item(app, db, event)
    _thumb(creator_client, event, item)
    assert (_folder(app, event) / "thumbs" / f"{item.id}-320.webp").is_file()


def test_thumb_320_landscape_scales_long_side_to_320(creator_client, app, db, event):
    item = _item(app, db, event, _jpeg(1000, 500))
    img = Image.open(io.BytesIO(_thumb(creator_client, event, item).data))
    assert img.size == (320, 160)


def test_thumb_960_scales_long_side_to_960(creator_client, app, db, event):
    item = _item(app, db, event, _jpeg(2000, 1000))
    img = Image.open(io.BytesIO(_thumb(creator_client, event, item, 960).data))
    assert img.size == (960, 480)


def test_thumb_exif_orientation_6_yields_portrait(creator_client, app, db, event):
    item = _item(app, db, event, _jpeg(200, 100, orientation=6))
    img = Image.open(io.BytesIO(_thumb(creator_client, event, item).data))
    assert img.height > img.width


def test_thumb_strips_exif_and_gps_from_derivative(creator_client, app, db, event):
    item = _item(app, db, event, _jpeg(gps=True, orientation=3))
    img = Image.open(io.BytesIO(_thumb(creator_client, event, item).data))
    assert (len(img.getexif()), "exif" in img.info) == (0, False)


def test_thumb_response_is_privately_cacheable_for_a_day(creator_client, app, db, event):
    item = _item(app, db, event)
    cache = _thumb(creator_client, event, item).headers["Cache-Control"]
    assert ("private" in cache, "max-age=86400" in cache, "public" in cache) == (True, True, False)


def test_thumb_conditional_request_with_etag_returns_304(creator_client, app, db, event):
    item = _item(app, db, event)
    etag = _thumb(creator_client, event, item).headers["ETag"]
    resp = creator_client.get(
        f"/e/{event.code}/media/{item.id}/thumb/320", headers={"If-None-Match": etag}
    )
    assert resp.status_code == 304


def test_thumb_unsupported_size_returns_404(creator_client, app, db, event):
    item = _item(app, db, event)
    assert _thumb(creator_client, event, item, 500).status_code == 404


def test_thumb_of_video_returns_404(creator_client, app, db, event):
    item = _item(
        app, db, event, b"\x00\x00\x00\x18ftypmp42" + b"0" * 20, name="v.mp4", mime="video/mp4"
    )
    assert _thumb(creator_client, event, item).status_code == 404


def test_thumb_of_corrupt_image_returns_404_not_500(creator_client, app, db, event):
    item = _item(app, db, event, b"\xff\xd8\xff not an image at all")
    assert _thumb(creator_client, event, item).status_code == 404


def test_thumb_of_decompression_bomb_returns_404_without_derivative(
    creator_client, app, db, event, monkeypatch
):
    monkeypatch.setattr("app.media.thumbs.MAX_PIXELS", 100)
    item = _item(app, db, event, _jpeg(200, 200))
    resp = _thumb(creator_client, event, item)
    assert (
        resp.status_code,
        (_folder(app, event) / "thumbs" / f"{item.id}-320.webp").exists(),
    ) == (404, False)


def test_thumb_png_with_alpha_returns_webp(creator_client, app, db, event):
    buf = io.BytesIO()
    Image.new("RGBA", (50, 50), (255, 0, 0, 80)).save(buf, "PNG")
    item = _item(app, db, event, buf.getvalue(), name="a.png", mime="image/png")
    assert _thumb(creator_client, event, item).status_code == 200


def test_thumb_without_access_redirects_like_file(client, app, db, event):
    item = _item(app, db, event)
    assert (
        _thumb(client, event, item).status_code
        == client.get(f"/e/{event.code}/media/{item.id}/file").status_code
    )


def test_thumb_for_guest_returns_200(guest_client, app, db, event):
    item = _item(app, db, event)
    assert _thumb(guest_client, event, item).status_code == 200


def test_thumb_of_other_event_media_returns_404(creator_client, app, db, event, creator):
    other = Event(
        code="OTHER123",
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(other)
    db.session.commit()
    item = _item(app, db, other)
    assert creator_client.get(f"/e/{event.code}/media/{item.id}/thumb/320").status_code == 404


def test_delete_media_removes_its_derivatives(creator_client, app, db, event):
    item = _item(app, db, event)
    _thumb(creator_client, event, item)
    _thumb(creator_client, event, item, 960)
    item_id = item.id
    creator_client.post(f"/e/{event.code}/media/{item_id}/delete")
    left = list((_folder(app, event) / "thumbs").glob(f"{item_id}-*"))
    assert left == []


def test_delete_event_purges_media_folder_with_derivatives(creator_client, app, db, event):
    item = _item(app, db, event)
    _thumb(creator_client, event, item)
    creator_client.post(f"/e/{event.code}/delete")
    assert not (Path(app.instance_path) / "media" / event.code).exists()


def test_export_zip_contains_originals_and_no_derivatives(creator_client, app, db, event):
    item = _item(app, db, event)
    _thumb(creator_client, event, item)
    resp = creator_client.get(f"/e/{event.code}/export")
    names = zipfile.ZipFile(io.BytesIO(resp.data)).namelist()
    assert sorted(n for n in names if n != "evenement.json") == ["medias/p.jpg"]


def test_thumb_not_counted_in_quota(creator_client, app, db, event):
    from app.freemium import get_media_quota

    item = _item(app, db, event)
    _thumb(creator_client, event, item)
    assert get_media_quota(event.creator).used_bytes == 0


# --- 26.2 formats ---------------------------------------------------------------------------------------------


def test_upload_heic_is_refused_with_clear_message(creator_client, event):
    resp = _upload(creator_client, event, HEIC, "IMG_1.HEIC", "image/heic")
    assert (
        resp.status_code,
        "Ce format n'est pas pris en charge" in resp.get_json()["message"],
    ) == (415, True)


def test_upload_heic_message_mentions_iphone_setting(creator_client, event):
    resp = _upload(creator_client, event, HEIC, "IMG_1.HEIC", "image/heic")
    assert "Le plus compatible" in resp.get_json()["message"]


def test_upload_heic_message_is_translated_in_english(creator_client, event):
    resp = _upload(creator_client, event, HEIC, "IMG_1.HEIC", "image/heic", query="?lang=en")
    assert "Most Compatible" in resp.get_json()["message"]


def test_upload_heic_declared_as_octet_stream_is_refused(creator_client, event):
    resp = _upload(creator_client, event, HEIC, "IMG_2.heic", "application/octet-stream")
    assert resp.status_code == 415


def test_upload_heic_disguised_as_jpeg_is_refused_and_not_stored(creator_client, event):
    _upload(creator_client, event, HEIC, "IMG_3.jpg", "image/jpeg")
    assert MediaItem.query.count() == 0


def test_gallery_upload_input_does_not_advertise_heic(creator_client, event):
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    accept = re.search(r'name="file"[^>]*accept="([^"]*)"', html).group(1)
    assert "heic" not in accept.lower()


def test_upload_png_content_declared_as_jpeg_is_refused(creator_client, event):
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "PNG")
    assert _upload(creator_client, event, buf.getvalue(), "a.jpg", "image/jpeg").status_code == 415


def test_upload_unknown_type_is_refused_with_format_message(creator_client, event):
    resp = _upload(creator_client, event, b"%PDF-1.4", "a.pdf", "application/pdf")
    assert resp.get_json()["message"].startswith("Ce format n'est pas pris en charge")


def test_upload_mp4_is_accepted(creator_client, event):
    data = b"\x00\x00\x00\x18ftypisom" + b"0" * 32
    assert _upload(creator_client, event, data, "v.mp4", "video/mp4").status_code == 201


def test_gallery_video_tile_shows_play_icon_without_loading_video(creator_client, app, db, event):
    _item(app, db, event, b"\x00\x00\x00\x18ftypisom" + b"0" * 20, name="v.mp4", mime="video/mp4")
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert ('data-testid="media-video-tile"' in html, "<video" in html) == (True, False)


# --- 26.3 envoi -----------------------------------------------------------------------------------------------


def test_upload_one_file_per_request_creates_one_item(creator_client, event):
    _upload(creator_client, event, _jpeg(), "a.jpg")
    assert MediaItem.query.count() == 1


def test_upload_json_success_returns_201_with_id(creator_client, event):
    resp = _upload(creator_client, event, _jpeg(), "a.jpg")
    assert (resp.status_code, resp.get_json()["ok"]) == (201, True)


def test_upload_two_files_without_js_creates_two_items(creator_client, event):
    creator_client.post(
        f"/e/{event.code}/media/upload",
        data={
            "file": [
                (io.BytesIO(_jpeg()), "a.jpg", "image/jpeg"),
                (io.BytesIO(_jpeg()), "b.jpg", "image/jpeg"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert MediaItem.query.count() == 2


def test_upload_global_caption_is_saved(creator_client, event):
    _upload(creator_client, event, _jpeg(), "a.jpg", caption="  Au sommet  ")
    assert MediaItem.query.one().caption == "Au sommet"


def test_upload_caption_is_cut_at_500_characters(creator_client, event):
    _upload(creator_client, event, _jpeg(), "a.jpg", caption="x" * 600)
    assert len(MediaItem.query.one().caption) == 500


def test_upload_too_large_returns_413_with_message(creator_client, event, monkeypatch):
    monkeypatch.setattr("app.media.MAX_FILE_SIZE", 10)
    resp = _upload(creator_client, event, _jpeg(), "a.jpg")
    assert (resp.status_code, "trop volumineux" in resp.get_json()["message"]) == (413, True)


def test_upload_quota_reached_by_creator_returns_409_with_honest_message(creator_client, event, db):
    from app.freemium import get_media_quota

    quota = get_media_quota(event.creator)
    quota.used_bytes = quota.max_bytes
    db.session.commit()
    resp = _upload(creator_client, event, _jpeg(), "a.jpg")
    message = resp.get_json()["message"]
    assert (resp.status_code, "Supprimez des médias" in message, "offre" in message) == (
        409,
        True,
        False,
    )


def test_upload_quota_reached_for_guest_tells_to_warn_organizer(guest_client, event, db):
    from app.freemium import get_media_quota

    quota = get_media_quota(event.creator)
    quota.used_bytes = quota.max_bytes
    db.session.commit()
    assert "organisateur" in _upload(guest_client, event, _jpeg(), "a.jpg").get_json()["message"]


def test_upload_consumes_quota_by_file_size(creator_client, event):
    from app.freemium import get_media_quota

    data = _jpeg()
    _upload(creator_client, event, data, "a.jpg")
    assert get_media_quota(event.creator).used_bytes == len(data)


def test_upload_rate_limit_allows_more_than_ten_per_hour(creator_client, event):
    codes = [
        _upload(creator_client, event, _jpeg(20, 20), f"{i}.jpg").status_code for i in range(12)
    ]
    assert set(codes) == {201}


def test_upload_rate_limit_returns_clean_429_after_200_requests(creator_client, event):
    limiter.reset()
    codes = [
        creator_client.post(
            f"/e/{event.code}/media/upload", headers={"Accept": "application/json"}
        ).status_code
        for _ in range(201)
    ]
    assert (set(codes[:200]), codes[200]) == ({400}, 429)


def test_upload_original_name_is_sanitized(creator_client, event):
    _upload(creator_client, event, _jpeg(), "../../etc/pass:w*d.jpg")
    assert MediaItem.query.one().original_name == "passwd.jpg"


def test_upload_extracts_gps_from_exif(creator_client, event):
    _upload(creator_client, event, _jpeg(gps=True), "g.jpg")
    item = MediaItem.query.one()
    assert (round(item.latitude, 3), round(item.longitude, 3)) == (48.857, 2.352)


def test_upload_extracts_taken_date_from_exif(creator_client, event):
    _upload(creator_client, event, _jpeg(gps=True), "g.jpg")
    assert MediaItem.query.one().taken_at == _dt(2024, 7, 14, 10, 20, 30)


def test_upload_requires_access_returns_redirect_for_json_client(client, event):
    assert _upload(client, event, _jpeg(), "a.jpg").status_code == 302


# --- Galerie --------------------------------------------------------------------------------------------------


def _tiles(html):
    return re.findall(r'data-testid="media-tile" data-media-id="(\w+)"', html)


def test_gallery_groups_tiles_by_taken_day(creator_client, app, db, event):
    for day, hour in ((14, 9), (14, 18), (13, 8)):
        _item(app, db, event, taken=_dt(2024, 7, day, hour))
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert re.findall(r'data-day="([\d-]+)"', html) == ["2024-07-14", "2024-07-13"]


def test_gallery_falls_back_to_upload_date_without_exif(creator_client, app, db, event):
    _item(app, db, event)
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert f'data-day="{datetime.utcnow().date().isoformat()}"' in html


def test_gallery_orders_newest_first(creator_client, app, db, event):
    old = _item(app, db, event, taken=_dt(2024, 7, 1))
    new = _item(app, db, event, taken=_dt(2024, 7, 9))
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert _tiles(html) == [new.id, old.id]


def test_gallery_tiles_load_thumbnails_not_originals(creator_client, app, db, event):
    item = _item(app, db, event)
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert (f"/media/{item.id}/thumb/320" in html, f"/media/{item.id}/file" in html) == (
        True,
        False,
    )


def test_gallery_tiles_are_lazy_async_with_reserved_dimensions(creator_client, app, db, event):
    _item(app, db, event)
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert ('loading="lazy" decoding="async"' in html, 'width="320" height="320"' in html) == (
        True,
        True,
    )


def test_gallery_shows_count(creator_client, app, db, event):
    _item(app, db, event)
    _item(app, db, event)
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert "Total : 2" in html


def test_gallery_first_page_has_60_tiles_and_show_more(creator_client, app, db, event):
    base = _dt(2024, 7, 1)
    for i in range(61):
        _item(app, db, event, b"x", taken=base + timedelta(minutes=i))
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert (len(_tiles(html)), 'data-testid="media-more"' in html) == (60, True)


def test_gallery_htmx_page_2_returns_remaining_tile_without_more_button(
    creator_client, app, db, event
):
    base = _dt(2024, 7, 1)
    for i in range(61):
        _item(app, db, event, b"x", taken=base + timedelta(minutes=i))
    html = creator_client.get(
        f"/e/{event.code}/media?page=2", headers={"HX-Request": "true"}
    ).get_data(as_text=True)
    assert (len(_tiles(html)), "media-more" in html, "<html" in html) == (1, False, False)


def test_gallery_page_2_does_not_repeat_the_day_heading_of_page_1(creator_client, app, db, event):
    for i in range(61):
        _item(app, db, event, b"x", taken=_dt(2024, 7, 1, 0, 0) + timedelta(minutes=i))
    html = creator_client.get(
        f"/e/{event.code}/media?page=2", headers={"HX-Request": "true"}
    ).get_data(as_text=True)
    assert "media-day" not in html


def test_gallery_upto_returns_enough_pages_to_reach_item(creator_client, app, db, event):
    base = _dt(2024, 7, 1)
    for i in range(70):
        _item(app, db, event, b"x", taken=base + timedelta(minutes=i))
    html = creator_client.get(f"/e/{event.code}/media?upto=65").get_data(as_text=True)
    assert len(_tiles(html)) == 70


def test_gallery_empty_state_has_testid_and_no_grid(creator_client, event):
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert ('data-testid="media-empty"' in html, 'data-testid="media-grid"' in html) == (
        True,
        False,
    )


def test_gallery_has_single_primary_add_button(creator_client, event):
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert len(re.findall(r'class="ui-btn ui-btn--primary[^"]*"[^>]*data-sheet-open', html)) == 1


def test_gallery_caption_is_exposed_as_tooltip_and_alt(creator_client, app, db, event):
    _item(app, db, event, caption="Sommet")
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert ('title="Sommet"' in html, 'alt="Sommet"' in html) == (True, True)


def test_gallery_alt_without_caption_names_the_author(creator_client, app, db, event):
    _item(app, db, event)
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert 'alt="Photo ajoutée par Camille"' in html


def test_gallery_creator_full_quota_shows_honest_note_without_payment_button(
    creator_client, event, db
):
    from app.freemium import get_media_quota

    quota = get_media_quota(event.creator)
    quota.used_bytes = quota.max_bytes
    db.session.commit()
    html = creator_client.get(f"/e/{event.code}/media").get_data(as_text=True)
    assert ("Supprimez des médias" in html, "data-upgrade" in html) == (True, False)


# --- Visionneuse ----------------------------------------------------------------------------------------------


@pytest.fixture
def three(app, db, event):
    """Trois médias, du plus récent (c) au plus ancien (a)."""
    return [_item(app, db, event, taken=_dt(2024, 7, d)) for d in (1, 2, 3)]


def _view(client, event, item):
    return client.get(f"/e/{event.code}/media/{item.id}").get_data(as_text=True)


def test_viewer_middle_item_links_prev_and_next_in_gallery_order(creator_client, event, three):
    a, b, c = three
    html = _view(creator_client, event, b)
    assert (
        f'rel="prev" class="ui-viewer__nav ui-viewer__nav--prev" href="/e/{event.code}/media/{c.id}"'
        in html,
        f'rel="next" class="ui-viewer__nav ui-viewer__nav--next" href="/e/{event.code}/media/{a.id}"'
        in html,
    ) == (True, True)


def test_viewer_first_item_has_no_prev(creator_client, event, three):
    assert 'rel="prev"' not in _view(creator_client, event, three[2])


def test_viewer_last_item_has_no_next(creator_client, event, three):
    assert 'rel="next"' not in _view(creator_client, event, three[0])


def test_viewer_shows_position_in_gallery(creator_client, event, three):
    assert "2 sur 3" in _view(creator_client, event, three[1])


def test_viewer_back_link_targets_gallery_item_anchor(creator_client, event, three):
    html = _view(creator_client, event, three[1])
    assert f'href="/e/{event.code}/media#m-{three[1].id}" data-testid="viewer-back"' in html


def test_viewer_back_link_asks_for_enough_pages_beyond_first_page(creator_client, app, db, event):
    base = _dt(2024, 7, 1)
    items = [_item(app, db, event, b"x", taken=base + timedelta(minutes=i)) for i in range(70)]
    html = _view(creator_client, event, items[0])
    assert f"/e/{event.code}/media?upto=70#m-{items[0].id}" in html


def test_viewer_image_uses_960_thumbnail_with_original_on_demand(creator_client, event, three):
    html = _view(creator_client, event, three[0])
    assert (
        f"/media/{three[0].id}/thumb/960" in html,
        f'data-original="/e/{event.code}/media/{three[0].id}/file"' in html,
    ) == (True, True)


def test_viewer_prefetches_next_image(creator_client, event, three):
    assert f'rel="prefetch" href="/e/{event.code}/media/{three[0].id}/thumb/960"' in _view(
        creator_client, event, three[1]
    )


def test_viewer_video_has_controls_metadata_preload_and_playsinline(creator_client, app, db, event):
    item = _item(
        app, db, event, b"\x00\x00\x00\x18ftypisom" + b"0" * 20, name="v.mp4", mime="video/mp4"
    )
    html = _view(creator_client, event, item)
    assert re.search(r"<video[^>]* controls preload=\"metadata\" playsinline", html)


def test_download_sends_original_as_attachment(creator_client, app, db, event):
    item = _item(app, db, event, name="Été 2024.jpg")
    resp = creator_client.get(f"/e/{event.code}/media/{item.id}/download")
    assert resp.headers["Content-Disposition"].startswith("attachment")


def test_download_filename_is_sanitized(creator_client, app, db, event):
    item = _item(app, db, event)
    item.original_name = '../../x"y\\z.jpg'
    db.session.commit()
    resp = creator_client.get(f"/e/{event.code}/media/{item.id}/download")
    assert "filename=z.jpg" in resp.headers["Content-Disposition"]


def test_download_of_other_event_media_returns_404(creator_client, app, db, event, creator):
    other = Event(
        code="OTHER456",
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(other)
    db.session.commit()
    item = _item(app, db, other)
    assert creator_client.get(f"/e/{event.code}/media/{item.id}/download").status_code == 404


def test_download_without_access_redirects(client, app, db, event):
    item = _item(app, db, event)
    assert client.get(f"/e/{event.code}/media/{item.id}/download").status_code == 302


def test_caption_edit_by_author_updates_caption(guest_client, app, db, event, guest):
    item = _item(app, db, event, uploaded_by=guest.id)
    guest_client.post(f"/e/{event.code}/media/{item.id}/caption", data={"caption": " Nouvelle "})
    db.session.refresh(item)
    assert item.caption == "Nouvelle"


def test_caption_edit_by_creator_updates_caption(
    creator_client, app, db, event, guest, creator_guest
):
    item = _item(app, db, event, uploaded_by=guest.id)
    creator_client.post(f"/e/{event.code}/media/{item.id}/caption", data={"caption": "Par l'orga"})
    db.session.refresh(item)
    assert item.caption == "Par l'orga"


def test_caption_edit_by_other_guest_is_forbidden(client, app, db, event, guest, other_guest_c):
    item = _item(app, db, event, uploaded_by=guest.id)
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = other_guest_c.id
    resp = client.post(f"/e/{event.code}/media/{item.id}/caption", data={"caption": "Piraté"})
    assert (resp.status_code, MediaItem.query.one().caption) == (403, "")


def test_caption_longer_than_500_is_rejected_and_kept(
    creator_client, app, db, event, creator_guest
):
    item = _item(app, db, event, caption="Avant")
    creator_client.post(f"/e/{event.code}/media/{item.id}/caption", data={"caption": "x" * 501})
    db.session.refresh(item)
    assert item.caption == "Avant"


def test_viewer_caption_form_shown_to_author_only(client, app, db, event, guest, other_guest_c):
    item = _item(app, db, event, uploaded_by=guest.id)
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = other_guest_c.id
    assert "viewer-edit-caption" not in _view(client, event, item)


def test_viewer_caption_form_shown_to_author(guest_client, app, db, event, guest):
    item = _item(app, db, event, uploaded_by=guest.id)
    assert "viewer-edit-caption" in _view(guest_client, event, item)


def test_viewer_delete_button_hidden_for_other_guest(client, app, db, event, guest, other_guest_c):
    item = _item(app, db, event, uploaded_by=guest.id)
    with client.session_transaction() as s:
        s[f"guest_{event.code}"] = other_guest_c.id
    assert "viewer-delete" not in _view(client, event, item)


def test_viewer_delete_button_asks_confirmation(creator_client, app, db, event, creator_guest):
    item = _item(app, db, event)
    html = _view(creator_client, event, item)
    assert re.search(
        r'<form[^>]*data-confirm="[^"]+"[^>]*>\s*<input[^>]*>\s*<button[^>]*viewer-delete', html
    )


def test_viewer_map_link_opens_openstreetmap_in_new_tab_safely(creator_client, app, db, event):
    item = _item(app, db, event, latitude=48.8566, longitude=2.3522)
    html = _view(creator_client, event, item)
    assert re.search(
        r'<a[^>]*target="_blank" rel="noopener noreferrer"[^>]*href="https://www\.openstreetmap\.org/\?mlat=48\.85660&amp;mlon=2\.35220',
        html,
    )


def test_viewer_without_location_shows_no_map_link(creator_client, app, db, event):
    item = _item(app, db, event)
    assert "viewer-map" not in _view(creator_client, event, item)


def test_viewer_loads_no_third_party_script_or_tile(creator_client, app, db, event):
    item = _item(app, db, event, latitude=1.0, longitude=2.0)
    html = _view(creator_client, event, item)
    assert re.findall(r'<(?:script|img|iframe)[^>]*src="https?://', html) == []


def test_viewer_shows_localized_taken_date(creator_client, app, db, event):
    item = _item(app, db, event, taken=_dt(2024, 7, 14, 10, 20))
    assert "Pris le 14 juillet 2024 · 10:20" in _view(creator_client, event, item)


def test_viewer_other_event_item_returns_404(creator_client, app, db, event, creator):
    other = Event(
        code="OTHER789",
        title="Autre",
        start_date=event.start_date,
        end_date=event.end_date,
        creator_id=creator.id,
        verified_at=datetime.utcnow(),
    )
    db.session.add(other)
    db.session.commit()
    item = _item(app, db, other)
    assert creator_client.get(f"/e/{event.code}/media/{item.id}").status_code == 404

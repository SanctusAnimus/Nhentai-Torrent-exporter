import math
import os
from re import compile, findall
from time import sleep
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger
from requests import get
import qbittorrentapi
from pathvalidate import sanitize_filepath
import psutil

author_re = compile(r"(?<=\[)[^\[\]]*(?=\])")
dir_name_re = compile(r'[^\w\-]')


def export_fav_ids(skip_torrent: bool = False):
    logger.info(f"Initiating export")

    if not is_process_running("qbittorrent"):
        raise SystemExit(f"Export requires QBittorrent to be running, please start QBittorrent first.")

    ids = []
    id_file_content = []
    by_author = {}

    index_delay = float(os.getenv("FAV_INDEX_DELAY", "2"))
    unknown_author_name = os.getenv("UNKNOWN_AUTHOR_NAME", "Unknown Author")
    base_url = "https://nhentai.net"
    current_url = f"{base_url}/favorites/"

    cookies = create_auth_cookies()

    while True:
        logger.info(f"Fetching {current_url}")
        fav_page_res = get(current_url, cookies=cookies, headers={"User-Agent": os.getenv("USER_AGENT")})
        if fav_page_res.status_code != 200:
            logger.error(f"Failed to fetch fav page at {current_url}: {fav_page_res.status_code} = {fav_page_res.text}")
            return

        soup = BeautifulSoup(fav_page_res.text, 'html.parser')

        fav_elements = soup.find_all(class_="gallery-favorite")

        for el in fav_elements:
            data_id = el["data-id"]
            caption_text = el.find(class_="caption").get_text()

            found_authors = findall(author_re, caption_text)
            if len(found_authors) > 0:
                author = found_authors[0]
            else:
                logger.warning(f"[{data_id}] {caption_text} has no author - recording and Unknown Author")
                author = unknown_author_name

            ids.append(data_id)
            row_entry = f"[{data_id}] | {caption_text}"
            id_file_content.append(row_entry)

            if author not in by_author:
                by_author[author] = set()

            entry = (data_id, caption_text)
            by_author[author].add(entry)

            logger.info(f"+ {data_id} {author} {caption_text}")

        pagination_el = soup.find(class_="pagination")
        next_el = pagination_el.find(class_="next")

        if next_el is None:
            logger.info("Next pagination el is missing, reached the end of favorites")
            break
        else:
            current_url = urljoin(current_url, next_el["href"])
            logger.info(f"Switching nav to {current_url}")
            sleep(index_delay)

    logger.info(f"Completed indexing favorites: {len(ids)} IDs, {len(by_author)} authors")

    with open("fav_ids.txt", "w", encoding="utf8") as fav_id_store:
        fav_id_store.write("\n".join(id_file_content))

    with open("fav_by_author.txt", "w", encoding="utf8") as fav_id_author_store:
        by_author = dict(sorted(by_author.items()))
        entries_count_total = 0
        for author_name, content in by_author.items():
            fav_id_author_store.write(author_name + "\n")
            fav_id_author_store.write("\n".join([f"\t[{entry[0]}] | {entry[1]}" for entry in content]))
            fav_id_author_store.write("\n")

            entries_count_total += len(content)

    estimated_duration = math.ceil(entries_count_total * (1 + float(os.getenv("FAV_TORRENT_DELAY", "2"))))
    logger.info(
        f"Completed flushing favorites index to disk ({entries_count_total} entries total), "
        f"estimated download time: {format_duration(estimated_duration)}"
    )

    if not skip_torrent:
        logger.info(
            f"Starting torrent download for {entries_count_total} entries, "
            f"ESTIMATED time:\n{format_duration(math.ceil(estimated_duration))}"
        )
        start_torrents_by_ids(by_author)
    else:
        logger.info(f"Skipping torrent download for {entries_count_total} entries due to CLI option")


def start_torrents_by_ids(author_index: dict[str, set[tuple[str, str]]]) -> None:
    client = create_qbittorrent_client()
    if client is None:
        return

    base_path = os.path.join(os.getcwd(), "fav_export")

    torrent_delay = float(os.getenv("FAV_TORRENT_DELAY", "2"))

    cookies = create_auth_cookies()

    for author_name, content in author_index.items():
        dir_path = os.path.join(base_path, author_name)
        os.makedirs(dir_path, exist_ok=True)

        for entry in content:
            create_torrent_entry(client, author_name, entry[0], cookies)
            sleep(torrent_delay)

    client.auth_log_out()


def create_torrent_entry(client: qbittorrentapi.Client, author: str, _id: str, cookies: dict[str, str]) -> bool:
    base_path = os.path.join(os.getcwd(), "fav_export", sanitize_filepath(author))
    logger.info(f"Creating torrent entry for <{_id}> into {base_path}")

    torrent_download_response = get(
        f"https://nhentai.net/g/{_id}/download",
        cookies=cookies,
        allow_redirects=True,
        headers={
            "User-Agent": os.getenv("USER_AGENT")
        })

    logger.info(f"Download status: {torrent_download_response.status_code}")

    if torrent_download_response.status_code != 200:
        logger.error(
            f"Failed to download torrent entry for <{_id}>: {torrent_download_response.status_code} "
            f"= {torrent_download_response.text}"
        )
        return False

    content = torrent_download_response.content

    add_res = client.torrents_add(torrent_files=content, save_path=base_path)

    logger.info(f"\t{_id} = {add_res}")

    with open(os.path.join(base_path, f"{_id}.torrent"), "wb") as f:
        f.write(content)

    return add_res == "Ok."


def create_qbittorrent_client() -> qbittorrentapi.Client | None:
    conn_info = dict(
        host="localhost",
        port=8080,
        username="admin",
        password="adminadmin",
    )
    qbt_client = qbittorrentapi.Client(**conn_info)
    try:
        qbt_client.auth_log_in()
        logger.info(f"Successfully logged into QBittorrent WebAPI")
        return qbt_client
    except qbittorrentapi.LoginFailed as e:
        logger.error(e)
        return None


def create_auth_cookies() -> dict[str, str]:
    return {
        "sessionid": os.getenv("SESSION_ID"),
        "cf_clearance": os.getenv("CF_CLEARANCE"),
        "csrftoken": os.getenv("CSRF_TOKEN"),
    }


def download_from_index_file(index_file: str = "fav_by_author.txt"):
    authors_data = {}
    current_author = None
    authors_count = 0
    entries_count = 0

    if not is_process_running("qbittorrent"):
        raise SystemExit(f"Export requires QBittorrent to be running, please start QBittorrent first.")

    logger.info(f"Starting download from author index file")

    with open(index_file, "r", encoding="utf8") as fav_src:
        for line in fav_src:
            if line[0] != "\t":
                current_author = sanitize_filepath(line.strip())
                authors_data[current_author] = set()
                authors_count += 1
            else:
                separator = line.find("|")
                _id = line[:separator].strip()[1:-1]
                entry_name = line[separator + 1:].strip()
                authors_data[current_author].add((_id, entry_name))
                entries_count += 1

    logger.info(f"Index {index_file} read: {authors_count=} {entries_count=}")

    start_torrents_by_ids(authors_data)


def is_process_running(process_name: str) -> bool:
    # Iterate over all running processes
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            # Check if the process name matches
            if process_name.lower() in proc.name().lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False


def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{str(hours).zfill(2)}h, {str(minutes).zfill(2)}m, {str(seconds).zfill(2)}s"

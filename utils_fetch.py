#!/user/bin/python3
#coding=utf-8


import os
import logging
import itertools
import shutil
from urllib.error import URLError
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen
from urllib.request import urlretrieve
from multiprocessing import Pool
from cssselect import GenericTranslator
from lxml.html import fromstring
# from datetime import datetime


_logger = logging.getLogger("fetch")
_logger.setLevel(logging.WARNING)
# logger.addHandler(logging.FileHandler('{:%Y%m%d%H%M%S}'.format(datetime.now()) + '.log', "w"))


def _get_gb2312_characters():
    # equivalent to level 2 of GBK
    higher_range = range(0xb0, 0xf7 + 1)
    lower_range = range(0xa1, 0xfe + 1)
    for higher in higher_range:
        for lower in lower_range:
            encoding = (higher << 8) | lower
            try:
                yield encoding.to_bytes(2, byteorder='big').decode(encoding='gb2312')
            except UnicodeDecodeError:
                hex_literal = '0x' + ''.join('%02x' % byte for byte in encoding.to_bytes(2, byteorder='big'))
                logging.warning('Unable to decode %s with GB2312' % hex_literal)
                pass


def _get_gbk_characters():
    # equivalent to the two-byte part of GB18030-2005
    higher_range_level2 = range(0xb0, 0xf7 + 1)
    lower_range_level2 = range(0xa1, 0xfe + 1)
    higher_range_level3 = range(0x81, 0xa0 + 1)
    lower_range_level3 = list(itertools.chain(range(0x40, 0x7f), range(0x7f + 1, 0xfe + 1)))
    higher_range_level4 = range(0xaa, 0xfe + 1)
    lower_range_level4 = list(itertools.chain(range(0x40, 0x7f), range(0x7f + 1, 0xa0 + 1)))

    gbk_ranges = {2: (higher_range_level2, lower_range_level2),
                  3: (higher_range_level3, lower_range_level3),
                  4: (higher_range_level4, lower_range_level4)}

    for level in [2, 3, 4]:
        (higher_range, lower_range) = gbk_ranges[level]
        for higher in higher_range:
            for lower in lower_range:
                encoding = (higher << 8) | lower
                try:
                    yield encoding.to_bytes(2, byteorder='big').decode(encoding='gbk')
                except UnicodeDecodeError:
                    hex_literal = '0x' + ''.join('%02x' % byte for byte in encoding.to_bytes(2, byteorder='big'))
                    logging.warning('Unable to decode %s with GBK' % hex_literal)
                    pass

# def get_gb18030_2005_characters():
#     return []


def _fetch_img_of_character(char, root_folder, dict_not_found):
    root_char = os.path.join(root_folder, char)
    if not os.path.exists(root_char):
        os.makedirs(root_char)

    url_root = 'http://www.chineseetymology.org'
    url = 'http://www.chineseetymology.org/CharacterEtymology.aspx?characterInput=' \
          + quote(char)

    attempts = 0
    max_attempts = 20
    while attempts < max_attempts:
        try:
            page = urlopen(url).read().decode('utf8')
            break
        except (TimeoutError, URLError, ConnectionError) as e:
            attempts += 1
            if isinstance(e, TimeoutError):
                msg = 'Time out when opening page %s. Retrying.' % url
            elif isinstance(e, URLError):
                msg = 'Error \"%s\" occurs when opening page %s. Retrying.' % (e.reason, url)
            elif isinstance(e, ConnectionError):
                msg = 'Error \"%s\" occurs when opening page %s. Retrying.' % (str(e), url)
            else:
                msg = 'Reached impossible branch.'
            _logger.warning(msg)

    if attempts == max_attempts:
        msg = 'Max attempts reached. Fail to open page ' + url
        _logger.error(msg)
        return

    page = fromstring(page)
    
    gt = GenericTranslator()
    seal_selector = gt.css_to_xpath("span#SealImages img")
    lst_selector = gt.css_to_xpath("span#LstImages img")
    bronze_selector = gt.css_to_xpath("span#BronzeImages img")
    oracle_selector = gt.css_to_xpath("span#OracleImages img")

    seal_img = [img.get('src') for img in page.xpath(seal_selector)]
    lst_img = [img.get('src') for img in page.xpath(lst_selector)]
    bronze_img = [img.get('src') for img in page.xpath(bronze_selector)]
    oracle_img = [img.get('src') for img in page.xpath(oracle_selector)]

    all_img = {"seal": seal_img, "lst": lst_img, "bronze": bronze_img, "oracle": oracle_img}

    for folder in all_img.keys():
        folder_full = os.path.join(root_char, folder)
        if not os.path.exists(folder_full):
            os.makedirs(folder_full)
        for img_src in all_img[folder]:
            (_, gif_name) = os.path.split(img_src)
            gif_full_path = os.path.join(folder_full, gif_name)
            if not os.path.exists(gif_full_path):
                img_url = url_root + img_src
                attempts = 0
                while attempts < max_attempts:
                    try:
                        urlretrieve(img_url, gif_full_path)
                        break
                    except TimeoutError:
                        msg = 'Time out when downloading %s to %s. Retrying.' % (img_url, gif_full_path)
                        _logger.warning(msg)
                    except HTTPError as e:
                        msg = 'Error \"%s\" occurs when downloading %s to %s' % (e.reason, img_url, gif_full_path)
                        if e.code == 404:
                            dict_not_found[gif_full_path] = img_url
                            _logger.warning(msg)
                            break
                        else:
                            msg += ' Retrying.'
                            _logger.warning(msg)
                    except URLError as e:
                        msg = 'Error \"%s\" occurs when downloading %s to %s. Retrying.' % (
                            e.reason, img_url, gif_full_path)
                        _logger.warning(msg)
                    except ConnectionError as e:
                        msg = 'Error \"%s\" occurs when downloading %s to %s. Retrying.' % (
                            str(e), img_url, gif_full_path)
                        _logger.warning(msg)

                if attempts == max_attempts:
                    msg = 'Max attempts reached. Fail to download image ' + img_url
                    _logger.error(msg)


def _remove_empty_characters(root_folder, not_analyzed_file_name):
    to_be_deleted = dict()
    for char in os.listdir(root_folder):
        char_path = os.path.join(root_folder, char)

        # from http://stackoverflow.com/a/1392549/688080
        size = sum(os.path.getsize(os.path.join(dir_path, file_name)) for (dir_path, dir_names, file_names) in
                   os.walk(char_path) for file_name in file_names)

        if size == 0:
            to_be_deleted[char_path] = char
    print("finish checking")
    with open(not_analyzed_file_name, "w",encoding="utf-8") as not_analyzed:
        for folder in to_be_deleted.keys():
            if not os.path.isdir(folder):
                continue
            not_analyzed.write(to_be_deleted[folder])
            shutil.rmtree(folder)


def _write_not_found(not_found_file_name, dict_not_found):
    with open(not_found_file_name, "w") as not_found_file:
        for (dst, src) in sorted(dict_not_found.items()):
            not_found_file.write('%s\t-/->\t%s\n' % (src, dst))

charset = "gbk"
character_count=None
thread_count=15


if character_count is None or (character_count is not None and character_count > 0):
    charset = charset.lower()
    if charset == "gb2312":
        characters = _get_gb2312_characters()
    elif charset == "gbk":
        characters = _get_gbk_characters()
    # elif charset == "gb18030":
    #     characters = get_gb18030_2005_characters()
    else:
        print("Only \"GB2312\" and \"GBK\" are accepted")
        sys.exit()

    if character_count is not None:
        characters = itertools.islice(characters, character_count)

    save_to_folder = charset
    if not os.path.exists(save_to_folder):
        os.mkdir(save_to_folder)
    not_analyzed_file_name = os.path.join(save_to_folder, "not_analyzed.txt")
    not_found_file_name = os.path.join(save_to_folder, "not_found.txt")
    if os.path.exists(not_analyzed_file_name):
        os.remove(not_analyzed_file_name)
    if os.path.exists(not_found_file_name):
        os.remove(not_found_file_name)

    not_found = dict()

def fetch_img(char):
    print(char.encode(charset))
    return _fetch_img_of_character(char, save_to_folder, not_found)

if __name__=="__main__":
    # pool = Pool(thread_count)
    # pool.map(fetch_img, characters)
    # pool.close()
    # pool.join()
    # for c in characters:
    #     fetch_img(c)

    _remove_empty_characters(save_to_folder, not_analyzed_file_name)
    _write_not_found(not_found_file_name, not_found)

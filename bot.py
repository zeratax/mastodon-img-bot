import argparse
import datetime
import logging
import sys
import json
from jsonschema import validate, RefResolver
import os
from collections import namedtuple
import shutil
import requests
from urllib.parse import urlsplit
import posixpath
import re

import tweepy
from pixivpy3 import *
from pybooru import Danbooru


logger = logging.getLogger("bot")
re_twitter = re.compile(r"https?://twitter\.com/\S+/\d+")
re_danbooru = re.compile(r"https?://danbooru\.donmai\.us/posts/\d+")
re_pixiv = re.compile(
    r"https?://(www)?.pixiv.net/member_illust\.php\?mode=medium&illust_id=\d+")


def get_error(e):
    exc_type, exc_obj, exc_tb = sys.exc_info()
    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
    return exc_type, fname, exc_tb.tb_lineno


def download_image(url):
    domain = "{0.netloc}".format(urlsplit(url))
    path = urlsplit(url).path
    filename = posixpath.basename(path)

    logger.info("downloading image...")

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:20.0) Gecko/20100101 Firefox/20.0'}
    response = requests.get(url, headers=headers, stream=True)

    file_path = "images/{}/{}".format(domain, filename)

    if not os.path.isdir("images/" + domain):
        os.makedirs("images/" + domain)
    with open(file_path, 'wb') as out_file:
        shutil.copyfileobj(
            response.raw, out_file)
    del response
    logger.debug("image downloaded!")

    return file_path


class BotClass():
    schema_config_path = "schema/config.json"
    schema_db_path = "schema/db.json"
    schema_image_path = "schema/image.json"
    db = {"images": []}

    def __init__(self, config):
        logger.info("loading config...")
        with open(self.schema_config_path) as data:
            self.schema_config = json.load(data)

        logger.debug("validating config...")
        validate(config, self.schema_config)
        self.settings = json.loads(
            json.dumps(config), object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))
        logger.debug("config is valid!")

        logger.debug(self.settings)

        self.load_images()
        self.login()

    def login(self):
        try:
            logger.info("login into twitter account...")
            auth = tweepy.OAuthHandler(self.settings.accounts.twitter.consumer_key,
                                       self.settings.accounts.twitter.consumer_secret)
            auth.set_access_token(self.settings.accounts.twitter.access_token,
                                  self.settings.accounts.twitter.access_token_secret)
            self.tweet_api = tweepy.API(auth)
        except AttributeError:
            self.tweet_api = False
        try:
            logger.info("login into danbooru account...")
            self.danbooru_api = Danbooru('danbooru',
                                         username=self.settings.accounts.danbooru.username,
                                         api_key=self.settings.accounts.danbooru.token)
        except AttributeError:
            self.danbooru_api = False
        try:
            logger.info("login into pixiv account...")
            self.pixiv_api = AppPixivAPI()
            self.pixiv_api.login(self.settings.accounts.pixiv.username,
                                 self.settings.accounts.pixiv.password)
        except AttributeError:
            self.pixiv_api = AppPixivAPI()

    def load_images(self):
        logger.info("loading images from: " + self.settings.db_path)
        with open(self.schema_db_path) as data:
            self.schema_db = json.load(data)

        if os.path.isfile(self.settings.db_path):
            with open(self.settings.db_path) as data:
                self.db = json.load(data)

        schema_path = 'file:///{0}/'.format(
            os.path.dirname(os.path.abspath(self.schema_db_path)).replace("\\", '/'))
        resolver = RefResolver(schema_path, self.schema_db)
        logger.debug("validating db...")
        validate(self.db, self.schema_db, resolver=resolver)
        logger.debug("db is valid!")

    def add_images(self):
        with open(self.schema_image_path) as data:
            self.schema_image = json.load(data)

        while True:
            logger.info("adding Image to db")
            logger.debug(self.db)
            paths = []
            source = input("enter image source:\n")
            exists = False
            handle = ""
            name = ""
            description = ""
            if source:
                for image in self.db["images"]:
                    if source == image["source"]:
                        exists = True
                        break
                if exists:
                    print("already added!")
                    continue
                if re_twitter.search(source) and self.tweet_api:
                    id = source.split('/')[-1]
                    tweet = self.tweet_api.get_status(id)

                    # print(tweet.extended_entities)
                    for image in tweet.extended_entities['media']:
                        file_url = image['media_url_https']

                        path = download_image(file_url)
                        paths.append(path)

                    handle = '@' + tweet.user.screen_name
                    name = tweet.user.name
                    description = tweet.text.rsplit(' ', 1)[0]
                elif re_danbooru.search(source):
                    if self.danbooru_api:
                        id = source.split("?")[0].split("/")[-1]
                        post = self.danbooru_api.post_show(id)
                    else:
                        resp = requests.get(url=source)
                        post = json.loads(resp.text)

                    try:
                        file_url = 'http://danbooru.donmai.us' + \
                            post['file_url']
                    except NameError:
                        file_url = post['source']
                    path = download_image(file_url)
                    paths.append(path)

                    name = post['tag_string_artist']
                    if post['pixiv_id']:
                        source = "https://www.pixiv.net/member_illust.php?mode=medium&illust_id=" + \
                            str(post['pixiv_id'])
                    if post['tag_string_copyright']:
                        description = '#' + \
                            post['tag_string_copyright'].replace(' ', ' #')

                    # get name and handle if possible from pixiv, check if api shows pawoo handle
                elif re_pixiv.search(source):
                    id = source.split('id=')[1]
                    illust = self.pixiv_api.illust_detail(
                        id, req_auth=True).illust

                    file_url = illust.image_urls[
                        'large'].replace("/c/600x1200_90", '')
                    path = "images/pixiv/" + id + ".jpg"
                    paths.append(path)

                    if not os.path.isdir("images/pixiv"):
                        os.makedirs("images/pixiv")
                    self.pixiv_api.download(
                        file_url, path="images/pixiv/", name=id + ".jpg")

                    name = illust.user['name']
                    handle = str(illust.user['id'])
                    description = illust.title + "\n" + illust.caption
                else:
                    while len(paths) < 4:
                        path = input(
                            "enter a relative image path or url:\n")
                        if path:
                            if not os.path.isfile(path):
                                path = download_image(path)
                            paths.append(path)
                        elif len(paths) > 0:
                            break
                    handle = input(
                        "enter english author name (optional):\n")
                    name = input(
                        "enter japanese author name (optional):\n")
                    description = input("enter description (optional)\n")
                image = {
                    "source": source,
                    "image_paths": paths,
                    "author": {
                        "handle": handle,
                        "name": name
                    },
                    "description": description
                }
                logger.debug("validating entered info")
                validate(image, self.schema_image)
                logger.debug("info is valid")
                self.db["images"].append(image)
                with open(self.settings.db_path, 'w') as output:
                    json.dump(self.db, output)
            else:
                break


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='discord bot')
    parser.add_argument("-c", "--config", help="Specify config file",
                        metavar="FILE")
    parser.add_argument("-a", "--add", help="Add images to database",
                        action="store_true")
    parser.add_argument("-v", "--verbose", help="increase output verbosity",
                        action="store_true")
    args = parser.parse_args()

    if args.verbose:
        print("verbose output enabled")
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    logFormatter = logging.Formatter(
        '%(asctime)s:%(levelname)s:%(name)s: %(message)s')
    consoleFormatter = logging.Formatter(
        '%(levelname)s:%(name)s: %(message)s')

    date = datetime.datetime.utcnow().strftime("%Y%m%d")
    time = datetime.datetime.utcnow().strftime("%X")
    if not os.path.isdir("log/{}".format(date)):
        os.makedirs("log/{}".format(date))
    if not os.path.isdir("images"):
        os.makedirs("images")

    handler = logging.FileHandler(filename="log/{}/{}.log".format(date, time),
                                  encoding="utf-8", mode='w')
    handler.setFormatter(logFormatter)
    logger.addHandler(handler)

    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(consoleFormatter)
    logger.addHandler(consoleHandler)

    if args.config:
        config_path = args.config
    while not os.path.isfile(config_path):
        config_path = input("Please enter a valid path to your config file:\n")

    with open(config_path) as data:
        data = json.load(data)
    bot = BotClass(data)

    if args.add:
        bot.add_images()

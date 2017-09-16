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
re_tweet =  re.compile(r"https?://twitter\.com\/(\S+)/status/\d+")
re_danbooru = re.compile(r"https?://danbooru\.donmai\.us/posts/\d+")
re_pixiv = re.compile(
    r"https?://(www)?.pixiv.net/member_illust\.php\?mode=medium&illust_id=\d+")


def error_info(e):
    """
    https://stackoverflow.com/a/1278740
    :param exception
    :returns type, file, and line number
    """
    exc_type, exc_obj, exc_tb = sys.exc_info()
    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
    return exc_type, fname, exc_tb.tb_lineno


def download_image(url):
    """
    :param url: string with the url to the image
    :return: string with the path to the saved image
    """
    domain = "{0.netloc}".format(urlsplit(url))
    path = urlsplit(url).path
    filename = posixpath.basename(path)

    logger.info("downloading image...")

    file_path = "images/{}/{}".format(domain, filename)
    if not os.path.isfile(file_path):
        # create folders based on domain name
        if not os.path.isdir("images/" + domain):
            os.makedirs("images/" + domain)

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:20.0) Gecko/20100101 Firefox/20.0'}
        response = requests.get(url, headers=headers, stream=True)

        with open(file_path, 'wb') as out_file:
            shutil.copyfileobj(
                response.raw, out_file)
        del response
        logger.info("image downloaded!")
    else:
        logger.info("image already downloaded")

    return file_path


class BotClass():
    schema_config_path = "schema/config.json"
    schema_db_path = "schema/db.json"
    schema_image_path = "schema/image.json"
    db = {"images": []}

    def __init__(self, config):
        logger.debug("loading config...")
        with open(self.schema_config_path) as data:
            self.schema_config = json.load(data)

        logger.debug("validating config...")
        validate(config, self.schema_config)
        logger.debug("config is valid!")
        # apply dictionary as properties of self.settings
        self.settings = json.loads(
            json.dumps(config), object_hook=lambda d: namedtuple('X', d.keys())(*d.values()))

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
            logger.debug("twitter credentials not definied")
            self.tweet_api = False
        try:
            logger.info("login into danbooru account...")
            self.danbooru_api = Danbooru('danbooru',
                                         username=self.settings.accounts.danbooru.username,
                                         api_key=self.settings.accounts.danbooru.token)
        except AttributeError:
            logger.debug("danbooru credentials not definied")
            self.danbooru_api = False
        try:
            logger.info("login into pixiv account...")
            self.pixiv_api = AppPixivAPI()
            self.pixiv_api.login(self.settings.accounts.pixiv.username,
                                 self.settings.accounts.pixiv.password)
        except AttributeError:
            logger.debug("pixiv credentials not definied")
            # self.pixiv_api = AppPixivAPI()
            self.pixiv_api = False

    def load_images(self):
        logger.debug("loading images from: " + self.settings.db_path)
        with open(self.schema_db_path) as data:
            self.schema_db = json.load(data)

        if os.path.isfile(self.settings.db_path):
            with open(self.settings.db_path) as data:
                self.db = json.load(data)

        # change relative paths to a absolute paths
        schema_path = 'file:///{0}/'.format(
            os.path.dirname(os.path.abspath(self.schema_db_path)).replace("\\", '/'))
        resolver = RefResolver(schema_path, self.schema_db)
        logger.debug("validating db...")
        validate(self.db, self.schema_db, resolver=resolver)
        logger.debug("db is valid!")
        # logger.debug("validating db...")
        # validate(self.db, self.schema_db)
        # logger.debug("db is valid!")

    def add_images(self):
        with open(self.schema_image_path) as data:
            self.schema_image = json.load(data)

        while True:
            logger.debug("adding Image to db")
            logger.debug(self.db)
            exists = False
            nsfw = False
            paths = []
            handle = ""
            name = ""
            description = ""
            source = input("enter image source (leave empty to abort):\n")
            if source:
                self.load_images()
                # check if image was already added
                for image in self.db["images"]:
                    if source == image["source"]:
                        exists = True
                        break
                if exists:
                    print("already added!")
                    continue
                # if url is part of these automatically retrieve image and
                # additional info
                if re_twitter.search(source) and self.tweet_api:
                    id = source.split('/')[-1]
                    tweet = self.tweet_api.get_status(id)
                    logger.debug(tweet)

                    # print(tweet.extended_entities)
                    for image in tweet.extended_entities['media']:
                        if image['type'] == 'photo':
                            file_url = image['media_url_https']

                            path = download_image(file_url)
                            paths.append(path)

                    handle = "@{}@twitter.com".format(tweet.user.screen_name)
                    name = tweet.user.name
                    # last word is always the shortened link to the media
                    if len(tweet.text.rsplit(' ', 1)):
                        description = tweet.text.rsplit(' ', 1)[0]
                    if tweet.possibly_sensitive:
                        nsfw = True
                elif re_danbooru.search(source):
                    if self.danbooru_api:
                        id = source.split("?")[0].split("/")[-1]
                        post = self.danbooru_api.post_show(id)
                    else:
                        url = source.split("?")[0] + ".json"
                        resp = requests.get(url)
                        post = json.loads(resp.text)
                    logger.debug(post)

                    try:
                        file_url = 'http://danbooru.donmai.us' + \
                            post['file_url']
                    except NameError:
                        file_url = post['source']
                    path = download_image(file_url)
                    paths.append(path)

                    # get name and handle if possible from pixiv, check if api
                    # shows pawoo handle
                    name = post['tag_string_artist']
                    if post['source']:
                        source = post['source']
                        if re_tweet.search(source):
                            username = re_tweet.search(source)[1]
                            handle = "@{}@twitter.com".format(username)
                    if post['pixiv_id']:
                        source = "https://www.pixiv.net/member_illust.php?mode=medium&illust_id=" + \
                            str(post['pixiv_id'])
                    if post['tag_string_copyright']:
                        description = '#' + \
                            post['tag_string_copyright'].replace(' ', ' #')
                    if post['rating'] is not "s":
                        nsfw = True

                    if self.pixiv_api and post['pixiv_id']:
                        illust = self.pixiv_api.illust_detail(
                            post['pixiv_id'], req_auth=True)
                        logger.debug(illust)
                        post = illust.illust
                        user = self.pixiv_api.user_detail(
                            post.user['id'], req_auth=True)
                        if user.profile['twitter_account']:
                            username = user.profile['twitter_account']
                            handle = "@{}@twitter.com".format(username)
                        if user.profile['pawoo_url']:
                            # resolve redirected url
                            r = requests.get(user.profile['pawoo_url'])
                            username = r.url.split("@")[1]
                            handle = "@{}@pawoo.net".format(username)
                elif re_pixiv.search(source) and self.pixiv_api:
                    # currently pixiv downloading only works while logged in to
                    # pixiv
                    id = source.split('id=')[1]
                    illust = self.pixiv_api.illust_detail(
                        id, req_auth=True)
                    logger.debug(illust)
                    post = illust.illust

                    file_url = post.image_urls[
                        'large'].replace("/c/600x1200_90", '')
                    path = "images/pixiv/" + id + ".jpg"
                    paths.append(path)

                    if not os.path.isdir("images/pixiv"):
                        os.makedirs("images/pixiv")
                    self.pixiv_api.download(
                        file_url, path="images/pixiv/", name=id + ".jpg")

                    name = post.user['name']
                    handle = str(post.user['id'])
                    user = self.pixiv_api.user_detail(int(handle), req_auth=True)
                    if user.profile['twitter_account']:
                        username = user.profile['twitter_account']
                        handle = "@{}@twitter.com".format(username)
                    if user.profile['pawoo_url']:
                        # resolve redirected url
                        r = requests.get(user.profile['pawoo_url'])
                        username = r.url.split("@")[1]
                        handle = "@{}@pawoo.net".format(username)

                    try:
                        description = illust.title
                        if post.tags:
                            description += "\n"
                    except AttributeError:
                        pass
                    for tag in post.tags:
                        description += '#' + tag['name'] + ' '
                    description = description[:-1]
                else:
                    # enter info manually
                    while len(paths) < 4:
                        path = input(
                            "enter a relative image path or url:\n")
                        if path:
                            # instead of posting images mastodon links can be boosted
                            if path == "mastodon":
                                paths.append(path + ".png") # to be still validatable
                                break
                            elif not os.path.isfile(path):
                                path = download_image(path)
                            paths.append(path)
                        elif paths:
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
                    "description": description,
                    "nsfw": nsfw
                }
                logger.debug("validating entered info...")
                validate(image, self.schema_image)
                logger.debug("info is valid")
                self.db["images"].append(image)
                with open(self.settings.db_path, 'w') as output:
                    json.dump(self.db, output)  # save to database
            else:
                break


if __name__ == '__main__':
    # add arguments
    parser = argparse.ArgumentParser(description='discord bot')
    parser.add_argument("-c", "--config", help="specify config file",
                        metavar="FILE")
    parser.add_argument("-a", "--add", help="add images to database",
                        action="store_true")
    parser.add_argument("-v", "--verbose", help="increase output verbosity",
                        action="store_true")
    args = parser.parse_args()

    # setup logging
    if args.verbose:
        print("verbose output enabled")
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    logFormatter = logging.Formatter(
        '%(asctime)s:%(levelname)s:%(name)s: %(message)s')
    consoleFormatter = logging.Formatter(
        '%(levelname)s:%(name)s: %(message)s')

    # setup folders
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

    # start bot with desired config
    if args.config:
        config_path = args.config
    while not os.path.isfile(config_path):
        config_path = input("Please enter a valid path to your config file:\n")

    with open(config_path) as data:
        data = json.load(data)
    bot = BotClass(data)

    # start bot in image adding mode
    if args.add:
        bot.add_images()

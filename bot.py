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
import random
import time
from urllib import parse

import schedule
from mastodon import Mastodon
import tweepy
from pixivpy3 import *
from pybooru import Danbooru


logger = logging.getLogger("bot")
re_twitter = re.compile(r"https?://twitter\.com/\S+/\d+")
re_tweet = re.compile(r"https?://twitter\.com\/(\S+)/status/\d+")
re_danbooru = re.compile(r"https?://danbooru\.donmai\.us/posts/\d+")
re_pixiv = re.compile(
    r"https?://(www)?.pixiv.net/member_illust\.php\?mode=medium&illust_id=\d+")
re_mastodon = re.compile(
    r"https?://(pawoo\.net|mastodon\.social|mstdn\.jp)/\S+/\d+")
re_link = re.compile(
    r"^(?:https?://)?[\w.-]+(?:\.[\w\.-]+)+[\w\-\._~:/?#[\]@!\$&'\(\)\*\+,;=.]+$")


def error_info(e):
    """
    https://stackoverflow.com/a/1278740
    :param exception
    :returns type, file, and line number
    """
    exc_type, exc_obj, exc_tb = sys.exc_info()
    fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
    return exc_type, fname, exc_tb.tb_lineno


def get_handle(username, domain="twitter.com"):
    handle = "@{}@{}".format(username, domain)
    return handle


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
        logger.info("login into mastodon bot...")
        self.mastodon_api = Mastodon(client_id=self.settings.client_id,
                                     client_secret=self.settings.client_secret,
                                     access_token=self.settings.access_token,
                                     api_base_url=self.settings.domain)
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

    def post_toot(self):
        logger.info("creating new toot...")
        self.load_images()
        image = {}
        while not image:
            logger.debug("choosing random image...")
            image = random.choice(self.db['images'])
            logger.debug(image)
            source = image['source']
            paths = image['image_paths']
            try:
                source = image['posted']
                posted = True
                # to reduce boosting repeat process in 70% of cases
                # if the image has already been posted
                if random.randint(0, 100) < 70:
                    image = {}
            except KeyError:
                posted = False
        # check if already posted or a mastodon link to boost original toot
        if paths[0] == "mastodon.png" or posted or re_mastodon.search(source):
            search = self.mastodon_api.search(source, resolve=True)
            logger.debug(search)
            status_id = search['statuses'][0]['id']
            logger.debug("toot id: " + str(status_id))
            logger.debug("boosting toot...")
            toot = self.mastodon_api.status_reblog(status_id)
        else:
            name = image['author']['name']
            handle = image['author']['handle']
            status = "Created by: {}({})\nSource: {}".format(
                name, handle, source)
            try:
                additional = image['additional']
                for link in additional:
                    status += "\n" + link
            except KeyError:
                pass
            try:
                description = image['description']
                status += "\n\n" + description[:400]
            except KeyError:
                pass
            try:
                nsfw = image['nsfw']
            except KeyError:
                nsfw = False

            media_ids = []
            for path in paths:
                logger.debug("'{}' uploading...".format(path))
                media = self.mastodon_api.media_post(media_file=path)
                media_ids.append(media['id'])
                logger.debug(media)

            logger.debug("posting toot...")
            try:
                cw = image['cw']
                toot = self.mastodon_api.status_post(status,
                                                     media_ids=media_ids,
                                                     sensitive=nsfw,
                                                     visibility='public',
                                                     spoiler_text=cw)
            except KeyError:
                toot = self.mastodon_api.status_post(status,
                                                     media_ids=media_ids,
                                                     sensitive=nsfw,
                                                     visibility='public')
        logger.debug(toot)
        image['posted'] = toot['url']
        logger.info(toot['url'])
        with open(self.settings.db_path, 'w') as output:
            json.dump(self.db, output)  # save to database
        logger.debug("toot url saved to db")
        # logger.debug(self.db)

    def scheduled_toots(self):
        logger.debug("posting toots every: {}min".format(
            self.settings.offset_min))
        schedule.every(self.settings.offset_min).minutes.do(self.post_toot)
        while True:
            try:
                schedule.run_pending()
            except Exception as e:
                logger.warning(repr(e))
                logger.warning(error_info(e))
            time.sleep(1)

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
            # logger.debug(self.db)

            source = input("enter image source (leave empty to abort):\n")
            if source:
                self.load_images()
                # check if image was already added
                if self.image_exists(source):
                    print("already added!")
                    continue  # jump into next loop
                # if url is part of these automatically retrieve image and
                # additional info
                if re_mastodon.search(source):
                    image = {
                        "source": source,
                        "image_paths": ["mastodon.png"],
                        "author": {
                            "handle": "",
                            "name": ""
                        },
                        "description": "",
                        "nsfw": False
                    }
                elif re_twitter.search(source) and self.tweet_api:
                    image = self.twitter_info(source)
                elif re_danbooru.search(source):
                    image = self.danbooru_info(source)
                elif re_pixiv.search(source) and self.pixiv_api:
                    # currently pixiv downloading only works while logged in to
                    # pixiv
                    image = self.pixiv_info(source)
                else:
                    # enter info manually
                    image = self.manual_info(source)
                if self.image_exists(image["source"]):
                    print("already added!")
                    continue  # jump into next loop

                logger.debug("validating entered info...")
                validate(image, self.schema_image)
                logger.debug("info is valid")

                self.db["images"].append(image)
                with open(self.settings.db_path, 'w') as output:
                    json.dump(self.db, output)  # save to database
                logger.info("{} images in db".format(len(self.db["images"])))
            else:
                break

    def manual_info(self, url):
        paths = []
        source = url.strip()
        additional = []
        link = ""

        while len(paths) < 4:
            path = input(
                "enter a relative image path or url:\n")
            if path:
                # instead of posting images mastodon links can be
                # boosted
                if path == "mastodon":
                    # to be still validatable
                    paths.append(path + ".png")
                    break
                elif not os.path.isfile(path):
                    path = download_image(path)
                paths.append(path)
            elif paths:
                break
        nsfw = input(
            "Is this image not safe for work: false/true (empty = false)\n")
        if nsfw.lower() == "true" or nsfw.lower() == "y" or nsfw.lower() == "yes":
            nsfw = True
        else:
            nsfw = False
        handle = input(
            "enter author handle, eg peterspark@pawoo.net (optional):\n")
        name = input(
            "enter author name (optional):\n")
        while True:
            link = input("Additional links? (optional):\n")
            additional.append(link)
            if not link.strip():
                break
        description = input("enter description (optional)\n")
        cw = input("enter content warnings (optional)\n")
        image = {
            "source": source,
            "image_paths": paths,
            "author": {
                "handle": handle.strip(),
                "name": name.strip()
            },
            "description": description.strip(),
            "nsfw": nsfw,
            "cw": cw.strip()
        }
        return image

    def twitter_info(self, url):
        nsfw = False
        paths = []
        handle = ""
        name = ""
        description = ""
        source = url

        id = source.split('/')[-1]
        tweet = self.tweet_api.get_status(id)
        logger.debug(tweet.extended_entities['media'])

        for media in tweet.extended_entities['media']:
            if media['type'] == 'photo':
                file_url = media['media_url_https']

                path = download_image(file_url)
                paths.append(path)
            else:
                file_url = media['video_info']['variants'][0]['url']

                path = download_image(file_url)
                paths.append(path)

        handle = "@{}@twitter.com".format(tweet.user.screen_name)
        name = tweet.user.name
        # last word is always the shortened link to the media
        if len(tweet.text.rsplit(' ', 1)):
            description = tweet.text.rsplit(' ', 1)[0]
        if tweet.possibly_sensitive:
            nsfw = True

        image = {
            "source": source,
            "image_paths": paths,
            "author": {
                "handle": handle.strip(),
                "name": name.strip()
            },
            "description": description.strip(),
            "nsfw": nsfw
        }
        return image

    def danbooru_info(self, url):
        nsfw = False
        paths = []
        handle = ""
        name = ""
        description = ""
        source = url.strip().split("?")[0]

        if self.danbooru_api:
            id = source.split("/")[-1]
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
            if re_link.search(parse.unquote(post['source'])):
                source = parse.unquote(post['source'])
            if re_tweet.search(source):
                username = re_tweet.search(source).group(1)
                handle = get_handle(username)
        if post['pixiv_id']:
            source = "https://www.pixiv.net/member_illust.php?mode=medium&illust_id=" + \
                str(post['pixiv_id'])
            pixiv = self.pixiv_info(source)
            source = pixiv["source"]
            if pixiv["author"]["handle"]:
                handle = pixiv["author"]["handle"]
            if pixiv["author"]["name"]:
                name = pixiv["author"]["name"]
        if post['tag_string_copyright']:
            description = '#' + \
                post['tag_string_copyright'].replace(' ', ' #').replace(
                    "#original", ' ').replace("_(series)", ' ').replace("-", "_")
        if post['rating'] is not "s":
            nsfw = True

        image = {
            "source": source,
            "image_paths": paths,
            "author": {
                "handle": handle.strip(),
                "name": name.strip()
            },
            "description": description.strip(),
            "nsfw": nsfw
        }
        return image

    def pixiv_info(self, url):
        nsfw = False
        paths = []
        handle = ""
        name = ""
        description = ""
        source = url.strip()

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
        user = self.pixiv_api.user_detail(
            int(handle), req_auth=True)
        if user.profile['twitter_account']:
            username = user.profile['twitter_account']
            handle = get_handle(username)
        if user.profile['pawoo_url']:
            # resolve redirected url
            r = requests.get(user.profile['pawoo_url'])
            username = r.url.split("@")[1]
            handle = get_handle(username, domain="pawoo.net")

        try:
            description = post.title
            if post.tags:
                description += "\n\n"
                for tag in post.tags:
                    tag = tag['name'].replace(
                        "/", "_").replace("-", "_")
                    description += '#' + tag + ' '
                description = description[:-1]
        except AttributeError:
            pass

        image = {
            "source": source,
            "image_paths": paths,
            "author": {
                "handle": handle.strip(),
                "name": name.strip()
            },
            "description": description.strip(),
            "nsfw": nsfw
        }
        return image

    def image_exists(self, source):
        exists = False
        for image in self.db["images"]:
            if source == image["source"]:
                exists = True
                break
        if exists:
            return True
        else:
            return False


if __name__ == '__main__':
    # add arguments
    parser = argparse.ArgumentParser(
        description='simple scheduled image bot for your mastodon instance')
    parser.add_argument("-c", "--config", help="specify config file",
                        metavar="FILE")
    parser.add_argument("-a", "--add", help="add images to database",
                        action="store_true")
    parser.add_argument("-p", "--post", help="post toot",
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
    date_str = datetime.datetime.utcnow().strftime("%Y%m%d")
    time_str = datetime.datetime.utcnow().strftime("%X")
    if not os.path.isdir("log/{}".format(date_str)):
        os.makedirs("log/{}".format(date_str))
    if not os.path.isdir("images"):
        os.makedirs("images")

    handler = logging.FileHandler(filename="log/{}/{}.log".format(date_str, time_str),
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

    # post a single toot
    if args.post:
        bot.post_toot()

    # start bot in scheduled toot mode
    if not args.add and not args.post:
        logger.info("starting scheduled toots")
        bot.scheduled_toots()

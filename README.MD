# Mastodon Image Bot
```
$ python bot.py -h
usage: bot.py [-h] [-c FILE] [-a] [-p] [-v]

simple scheduled image bot for your mastodon instance

optional arguments:
  -h, --help            show this help message and exit
  -c FILE, --config FILE
                        specify config file
  -a, --add             add images to database
  -p, --post            post toot
  -v, --verbose         increase output verbosity

```

## Setup
  1. install the requirements.txt `pip install -r requirements.txt`
  2. copy `config.example.json` to `config.json` and edit it to fit your configuration
  3. add images to your db with
    `python bot.py --config config.json --add`
    and just follow the instructions on screen or manually edited the json file
  4. When your finished start the bot with `python bot.py -c config.json`

### Acquiring tokens
To get `client_secret`, `client_id` and `access_token` you need to create an application at your mastodon instance.
You can either:
  - start `python create_app.py` and follow the instructions

  - or follow this guide: https://gist.github.com/aparrish/661fca5ce7b4882a8c6823db12d42d26

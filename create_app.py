from mastodon import Mastodon

domain = input("enter the domain of your mastodon instance:\n")
app = input("enter a name for your application:\n")

secret = Mastodon.create_app(app,
                             scopes=['read', 'write'],
                             api_base_url="https://botsin.space")
print("-----\ncopy the client_id and client_secret to your config\n-----")
print(secret)

api = Mastodon(secret[0], secret[1], api_base_url="https://botsin.space")

email = input("enter your email for the bot:\n")
password = input("enter your password for the bot:\n")

token = api.log_in(email, password, scopes=["read", "write"])
print("-----\ncopy the access_token to your config\n-----")
print(token)

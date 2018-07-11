import random
import re
import string

import asyncio
import asyncpg
import discord

from pluralkit import db
from pluralkit.bot import client, logger


def generate_hid() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=5))


async def parse_mention(mention: str) -> discord.User:
    # First try matching mention format
    match = re.fullmatch("<@!?(\\d+)>", mention)
    if match:
        try:
            return await client.get_user_info(match.group(1))
        except discord.NotFound:
            return None

    # Then try with just ID
    try:
        return await client.get_user_info(str(int(mention)))
    except (ValueError, discord.NotFound):
        return None


async def get_system_fuzzy(conn, key) -> asyncpg.Record:
    if isinstance(key, discord.User):
        return await db.get_system_by_account(conn, account_id=key.id)

    if isinstance(key, str) and len(key) == 5:
        return await db.get_system_by_hid(conn, system_hid=key)

    system = parse_mention(key)

    if system:
        return system
    return None


async def get_member_fuzzy(conn, system_id: int, key: str, system_only=True) -> asyncpg.Record:
    # First search by hid
    if system_only:
        member = await db.get_member_by_hid_in_system(conn, system_id=system_id, member_hid=key)
    else:
        member = await db.get_member_by_hid(conn, member_hid=key)
    if member is not None:
        return member

    # Then search by name, if we have a system
    if system_id:
        member = await db.get_member_by_name(conn, system_id=system_id, member_name=key)
        if member is not None:
            return member

command_map = {}

# Command wrapper
# Return True for success, return False for failure
# Second parameter is the message it'll send. If just False, will print usage


def command(cmd, subcommand, usage=None, description=None):
    def wrap(func):
        async def wrapper(conn, message, args):
            res = await func(conn, message, args)

            if res is not None:
                if not isinstance(res, tuple):
                    success, msg = res, None
                else:
                    success, msg = res

                if not success and not msg:
                    # Failure, no message, print usage
                    usage_embed = discord.Embed()
                    usage_embed.colour = discord.Colour.blue()
                    usage_embed.add_field(
                        name="Usage", value=usage, inline=False)

                    await client.send_message(message.channel, embed=usage_embed)
                elif not success:
                    # Failure, print message
                    error_embed = discord.Embed()
                    error_embed.colour = discord.Colour.dark_red()
                    error_embed.description = msg
                    await client.send_message(message.channel, embed=error_embed)
                elif msg:
                    # Success, print message
                    success_embed = discord.Embed()
                    success_embed.colour = discord.Colour.blue()
                    success_embed.description = msg
                    await client.send_message(message.channel, embed=success_embed)
                # Success, don't print anything
        if cmd not in command_map:
            command_map[cmd] = {}
        if subcommand not in command_map[cmd]:
            command_map[cmd][subcommand] = {}

        command_map[cmd][subcommand] = (wrapper, usage, description)
        return wrapper
    return wrap

# Member command wrapper
# Tries to find member by first argument
# If system_only=False, allows members from other systems by hid


def member_command(cmd, subcommand, usage=None, description=None, system_only=True):
    def wrap(func):
        async def wrapper(conn, message, args):
            # Return if no member param
            if len(args) == 0:
                return False

            # If system_only, we need a system to check
            system = await db.get_system_by_account(conn, message.author.id)
            if system_only and system is None:
                return False, "No system is registered to this account."

            # System is allowed to be none if not system_only
            system_id = system["id"] if system else None
            # And find member by key
            member = await get_member_fuzzy(conn, system_id=system_id, key=args[0], system_only=system_only)

            if member is None:
                return False, "Can't find member \"{}\".".format(args[0])

            return await func(conn, message, member, args[1:])
        return command(cmd=cmd, subcommand=subcommand, usage=usage, description=description)(wrapper)
    return wrap


async def generate_system_info_card(conn, system: asyncpg.Record) -> discord.Embed:
    card = discord.Embed()

    if system["name"]:
        card.title = system["name"]

    if system["description"]:
        card.add_field(name="Description",
                       value=system["description"], inline=False)

    if system["tag"]:
        card.add_field(name="Tag", value=system["tag"])

    # Get names of all linked accounts
    async def get_name(account_id):
        account = await client.get_user_info(account_id)
        return "{}#{}".format(account.name, account.discriminator)

    account_name_futures = []
    for account_id in await db.get_linked_accounts(conn, system_id=system["id"]):
        account_name_futures.append(get_name(account_id))
    # Run in parallel
    account_names = await asyncio.gather(*account_name_futures)

    card.add_field(name="Linked accounts", value=", ".join(account_names))

    # Get names of all members
    member_texts = []
    for member in await db.get_all_members(conn, system_id=system["id"]):
        member_texts.append("`{}`: {}".format(member["hid"], member["name"]))

    if len(member_texts) > 0:
        card.add_field(name="Members", value="\n".join(
            member_texts), inline=False)

    card.set_footer(text="System ID: {}".format(system["hid"]))
    return card


async def generate_member_info_card(conn, member: asyncpg.Record) -> discord.Embed:
    card = discord.Embed()
    card.set_author(name=member["name"], icon_url=member["avatar_url"])

    if member["color"]:
        card.colour = int(member["color"], 16)

    if member["birthday"]:
        card.add_field(name="Birthdate",
                       value=member["birthday"].strftime("%b %d, %Y"))

    if member["pronouns"]:
        card.add_field(name="Pronouns", value=member["pronouns"])

    if member["prefix"] or member["suffix"]:
        prefix = member["prefix"] or ""
        suffix = member["suffix"] or ""
        card.add_field(name="Proxy Tags",
                       value="{}text{}".format(prefix, suffix))

    if member["description"]:
        card.add_field(name="Description",
                       value=member["description"], inline=False)

    # Get system name and hid
    system = await db.get_system(conn, system_id=member["system"])
    if system["name"]:
        system_value = "`{}`: {}".format(system["hid"], system["name"])
    else:
        system_value = "`{}`".format(system["hid"])
    card.add_field(name="System", value=system_value, inline=False)

    card.set_footer(text="System ID: {} | Member ID: {}".format(
        system["hid"], member["hid"]))
    return card


async def text_input(message, subject):
    await client.send_message(message.channel, "Reply in this channel with the new description you want to set for {}.".format(subject))
    msg = await client.wait_for_message(author=message.author, channel=message.channel)

    await client.send_message(message.channel, "Alright. When you're happy with the new description, click the ✅ reaction. To cancel, click the ❌ reaction.")
    await client.add_reaction(msg, "✅")
    await client.add_reaction(msg, "❌")

    reaction = await client.wait_for_reaction(emoji=["✅", "❌"], message=msg, user=message.author)
    if reaction.reaction.emoji == "✅":
        return msg.content
    else:
        await client.clear_reactions(msg)
        return None
import time

import asyncpg
import asyncpg.exceptions

from pluralkit.bot import logger


async def connect():
    while True:
        try:
            return await asyncpg.create_pool(user="postgres", password="postgres", database="postgres", host="db")
        except (ConnectionError, asyncpg.exceptions.CannotConnectNowError):
            pass


def db_wrap(func):
    async def inner(*args, **kwargs):
        before = time.perf_counter()
        res = await func(*args, **kwargs)
        after = time.perf_counter()

        logger.debug(" - DB took {:.2f} ms".format((after - before) * 1000))
        return res
    return inner


webhook_cache = {}


@db_wrap
async def create_system(conn, system_name: str, system_hid: str):
    logger.debug("Creating system (name={}, hid={})".format(
        system_name, system_hid))
    return await conn.fetchrow("insert into systems (name, hid) values ($1, $2) returning *", system_name, system_hid)


@db_wrap
async def remove_system(conn, system_id: int):
    logger.debug("Deleting system (id={})".format(system_id))
    await conn.execute("delete from systems where id = $1", system_id)


@db_wrap
async def create_member(conn, system_id: int, member_name: str, member_hid: str):
    logger.debug("Creating member (system={}, name={}, hid={})".format(
        system_id, member_name, member_hid))
    return await conn.fetchrow("insert into members (name, system, hid) values ($1, $2, $3) returning *", member_name, system_id, member_hid)


@db_wrap
async def delete_member(conn, member_id: int):
    logger.debug("Deleting member (id={})".format(member_id))
    await conn.execute("update switches set member = null, member_del = true where member = $1", member_id)
    await conn.execute("delete from members where id = $1", member_id)


@db_wrap
async def link_account(conn, system_id: int, account_id: str):
    logger.debug("Linking account (account_id={}, system_id={})".format(
        account_id, system_id))
    await conn.execute("insert into accounts (uid, system) values ($1, $2)", int(account_id), system_id)


@db_wrap
async def unlink_account(conn, system_id: int, account_id: str):
    logger.debug("Unlinking account (account_id={}, system_id={})".format(
        account_id, system_id))
    await conn.execute("delete from accounts where uid = $1 and system = $2", int(account_id), system_id)


@db_wrap
async def get_linked_accounts(conn, system_id: int):
    return [row["uid"] for row in await conn.fetch("select uid from accounts where system = $1", system_id)]


@db_wrap
async def get_system_by_account(conn, account_id: str):
    return await conn.fetchrow("select systems.* from systems, accounts where accounts.uid = $1 and accounts.system = systems.id", int(account_id))


@db_wrap
async def get_system_by_hid(conn, system_hid: str):
    return await conn.fetchrow("select * from systems where hid = $1", system_hid)


@db_wrap
async def get_system(conn, system_id: int):
    return await conn.fetchrow("select * from systems where id = $1", system_id)


@db_wrap
async def get_member_by_name(conn, system_id: int, member_name: str):
    return await conn.fetchrow("select * from members where system = $1 and name = $2", system_id, member_name)


@db_wrap
async def get_member_by_hid_in_system(conn, system_id: int, member_hid: str):
    return await conn.fetchrow("select * from members where system = $1 and hid = $2", system_id, member_hid)


@db_wrap
async def get_member_by_hid(conn, member_hid: str):
    return await conn.fetchrow("select * from members where hid = $1", member_hid)


@db_wrap
async def get_member(conn, member_id: int):
    return await conn.fetchrow("select * from members where id = $1", member_id)


@db_wrap
async def get_message(conn, message_id: str):
    return await conn.fetchrow("select * from messages where mid = $1", message_id)


@db_wrap
async def update_system_field(conn, system_id: int, field: str, value):
    logger.debug("Updating system field (id={}, {}={})".format(
        system_id, field, value))
    await conn.execute("update systems set {} = $1 where id = $2".format(field), value, system_id)


@db_wrap
async def update_member_field(conn, member_id: int, field: str, value):
    logger.debug("Updating member field (id={}, {}={})".format(
        member_id, field, value))
    await conn.execute("update members set {} = $1 where id = $2".format(field), value, member_id)


@db_wrap
async def get_all_members(conn, system_id: int):
    return await conn.fetch("select * from members where system = $1", system_id)


@db_wrap
async def get_members_exceeding(conn, system_id: int, length: int):
    return await conn.fetch("select * from members where system = $1 and length(name) >= $2", system_id, length)


@db_wrap
async def get_webhook(conn, channel_id: str):
    if channel_id in webhook_cache:
        return webhook_cache[channel_id]
    res = await conn.fetchrow("select webhook, token from webhooks where channel = $1", int(channel_id))
    webhook_cache[channel_id] = res
    return res


@db_wrap
async def add_webhook(conn, channel_id: str, webhook_id: str, webhook_token: str):
    logger.debug("Adding new webhook (channel={}, webhook={}, token={})".format(
        channel_id, webhook_id, webhook_token))
    await conn.execute("insert into webhooks (channel, webhook, token) values ($1, $2, $3)", int(channel_id), int(webhook_id), webhook_token)


@db_wrap
async def add_message(conn, message_id: str, channel_id: str, member_id: int, sender_id: str):
    logger.debug("Adding new message (id={}, channel={}, member={}, sender={})".format(
        message_id, channel_id, member_id, sender_id))
    await conn.execute("insert into messages (mid, channel, member, sender) values ($1, $2, $3, $4)", int(message_id), int(channel_id), member_id, int(sender_id))


@db_wrap
async def get_members_by_account(conn, account_id: str):
    # Returns a "chimera" object
    return await conn.fetch("select members.id, members.hid, members.prefix, members.suffix, members.name, members.avatar_url, systems.tag from systems, members, accounts where accounts.uid = $1 and systems.id = accounts.system and members.system = systems.id", int(account_id))


@db_wrap
async def get_message_by_sender_and_id(conn, message_id: str, sender_id: str):
    await conn.fetchrow("select * from messages where mid = $1 and sender = $2", int(message_id), int(sender_id))


@db_wrap
async def delete_message(conn, message_id: str):
    logger.debug("Deleting message (id={})".format(message_id))
    await conn.execute("delete from messages where mid = $1", int(message_id))


async def create_tables(conn):
    await conn.execute("""create table if not exists systems (
        id          serial primary key,
        hid         char(5) unique not null,
        name        text,
        description text,
        tag         text,
        created     timestamp not null default current_timestamp
    )""")
    await conn.execute("""create table if not exists members (
        id          serial primary key,
        hid         char(5) unique not null,
        system      serial not null references systems(id) on delete cascade,
        color       char(6),
        avatar_url  text,
        name        text not null,
        birthday    date,
        pronouns    text,
        description text,
        prefix      text,
        suffix      text,
        created     timestamp not null default current_timestamp
    )""")
    await conn.execute("""create table if not exists accounts (
        uid         bigint primary key,
        system      serial not null references systems(id) on delete cascade
    )""")
    await conn.execute("""create table if not exists messages (
        mid         bigint primary key,
        channel     bigint not null,
        member      serial not null references members(id) on delete cascade,
        sender      bigint not null references accounts(uid)
    )""")
    await conn.execute("""create table if not exists switches (
        id          serial primary key,
        system      serial not null references systems(id) on delete cascade,
        member      serial references members(id) on delete restrict,
        timestamp   timestamp not null default current_timestamp,
        member_del  bool default false
    )""")
    await conn.execute("""create table if not exists webhooks (
        channel     bigint primary key,
        webhook     bigint not null,
        token       text not null
    )""")
    await conn.execute("""create table if not exists servers (
        id          bigint primary key,
        cmd_chans   bigint[],
        proxy_chans bigint[]
    )""")
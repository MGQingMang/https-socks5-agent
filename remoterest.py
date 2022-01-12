import aiosqlite
import logging
import signal

from sanic import Sanic
from sanic import response
from sanic import exceptions

app = Sanic('RemoteProxyAdmin')
app.config.DB_NAME = 'user.db'

@app.exception(exceptions.NotFound)
async def ignore_404(req, exc):
    return response.text('errUrl', status=404)

@app.get("/user/select")
async def select(req):
    userList = list()
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        async with db.execute("select name, password, bandwidth from user;") as cursor:
            async for row in cursor:
                user = {'name':row[0], 'password':row[1], 'bandwidth':row[2]}
                log.debug(f'{user}')
                userList.append(user)
    return response.json(userList)

@app.get("/user/insert")
async def insert(req):
    name = req.json['name']
    password = req.json['password']
    bandwidth = req.json['bandwidth']
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        async with db.execute("select name, password, bandwidth from user where name = ?", (name, )) as cursor:
            if(await cursor.fetchone()):
                log.debug(f'insert failed')
                return response.json({
                    "result": "insert failed"
                })
            else:
                await db.execute("insert into user values(?, ?, ?)", (name, password, bandwidth))
                await db.commit()
                log.debug(f'insert success')
                return response.json({
                    "result": "insert success"
                })

@app.get("/user/delete")
async def delete(req):
    name = req.json['name']
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        async with db.execute("select name, password, bandwidth from user where name = ?", (name, )) as cursor:
            if(await cursor.fetchone()):
                await db.execute("delete from user where name = ?", (name, ))
                await db.commit()
                log.debug(f'delete success')
                return response.json({
                    "result": "delete success"
                })
            else:
                log.debug(f'delete failed')
                return response.json({
                    "result": "delete failed"
                })

@app.get("/user/update")
async def update(req):
    name = req.json['name']
    password = req.json['password']
    bandwidth = req.json['bandwidth']
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        async with db.execute("select name, password, bandwidth from user where name = ?", (name, )) as cursor:
            if(await cursor.fetchone()):
                await db.execute("update user set password = ? where name = ?", (password, name))
                await db.execute("update user set bandwidth = ? where name = ?", (bandwidth, name))
                await db.commit()
                log.debug(f'update success')
                return response.json({
                    "result": "update success"
                })
            else:
                log.debug(f'update failed')
                return response.json({
                    "result": "update failed"
                })

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)

    app.run(host="0.0.0.0", port=8000)
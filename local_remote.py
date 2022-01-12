import argparse
import asyncio
import ipaddress
import logging
import os
import signal
import struct
import sys
import traceback
import aiosqlite3
import time
import websockets
from enum import Enum
ReadMode = Enum('ReadMod', ('EXACT', 'LINE', 'MAX', 'UNTIL'))

from http.server import BaseHTTPRequestHandler
from io import BytesIO

class HTTPRequest(BaseHTTPRequestHandler):
    def __init__(self, request_text):
        self.rfile = BytesIO(request_text)
        self.raw_requestline = self.rfile.readline()
        self.error_code = self.error_message = None
        self.parse_request()

    def send_error(self, code, message):
        self.error_code = code
        self.error_message = message
class MyError(Exception):
    pass

gSendBandwidth = 0
gRecvBandwidth = 0

async def localConsole(ws, path):
    global gSendBandwidth
    global gRecvBandwidth
    try:
        while True:
            gSendBandwidth = 0
            gRecvBandwidth = 0
            await asyncio.sleep(1)
            msg = await ws.send(f'{gSendBandwidth} {gRecvBandwidth}')
    except websockets.exceptions.ConnectionClosedError as exc:
        log.error(f'{exc}')
    except websockets.exceptions.ConnectionClosedOK as exc:
        log.error(f'{exc}')
    except Exception:
        log.error(f'{traceback.format_exc()}')
        exit(1)

async def xferDataSend(srcR, dstW, *, logHint=None):
    try:
        while True:
            data = await aioRead(srcR, ReadMode.MAX, maxLen=65535, logHint='')
            global gSendBandwidth
            gSendBandwidth += len(data)
            await aioWrite(dstW, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(dstW, logHint=logHint)

async def xferDataRecv(srcR, dstW, *, logHint=None):
    try:
        while True:
            data = await aioRead(srcR, ReadMode.MAX, maxLen=65535, logHint='')
            global gRecvBandwidth
            gRecvBandwidth += len(data)
            await aioWrite(dstW, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(dstW, logHint=logHint)

async def xferDataTokenBucket(srcR, dstW, bandwidth, *, logHint=None):
    try:
        capacity = 10 * bandwidth
        token = capacity
        time_last = time.time()
        time_now = time_last
        while True:
            data = await aioRead(srcR, ReadMode.MAX, maxLen=65535, logHint='')
            time_now = time.time()
            token += bandwidth * (time_now - time_last)
            time_last = time_now
            token = min(token, capacity)
            if token >= len(data):
                token -= len(data)
                await aioWrite(dstW, data, logHint='')
                          
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(dstW, logHint=logHint)

async def doClient(clientR, clientW):
    serverR, serverW = None, None
    try:
        clientHost, clientPort, *_ = clientW.get_extra_info('peername')
        logHint = f'{clientHost} {clientPort}'
        first = await aioRead(clientR, ReadMode.EXACT, exactLen=1, logHint=f'1stByte')
        if b'C' == first:
            request_text = await aioRead(clientR, ReadMode.UNTIL, untilSep=b'\r\n\r\n', logHint='msg')
            request_text = first + request_text
            request = HTTPRequest(request_text)
            if request.error_code == None:
                if request.command == "CONNECT":
                    proxyType = 'HTTPS'
                    logHint = f'{logHint} {proxyType}'
                    dstHost, dstPort, *_ = request.path.split(':')
                    proto = request.request_version
                else:
                    raise MyError(f'RECV INVALID={request_text.error_code} EXPECT=None')    
            else:
                raise MyError(f'RECV INVALID={request_text.command} EXPECT=CONNECT')
        elif b'\x05' == first:
            proxyType = 'SOCKS5'
            logHint = f'{logHint} {proxyType}'
            numMethods = await aioRead(clientR, ReadMode.EXACT, exactLen=1, logHint='nMethod')
            await aioRead(clientR, ReadMode.EXACT, exactLen=numMethods[0], logHint='methods')
            await aioWrite(clientW, b'\x05\x00', logHint='method.noAuth')

            await aioRead(clientR, ReadMode.EXACT, exactData=b'\x05\x01\x00', logHint='verCmdRsv')
            atyp = await aioRead(clientR, ReadMode.EXACT, exactLen=1, logHint='atyp')
            dstHost = None

            if atyp == b'\x01':
                dstHost = await aioRead(clientR, ReadMode.EXACT, exactLen=4, logHint=f'{logHint} ipv4')
                dstHost = str(ipaddress.ip_address(dstHost))
            elif atyp == b'\x03':
                dataLen = await aioRead(clientR, ReadMode.EXACT, exactLen=1, logHint=f'{logHint} fqdnLen')
                dataLen = dataLen[0]
                dstHost = await aioRead(clientR, ReadMode.EXACT, exactLen=dataLen, logHint=f'{logHint} fqdn')
                dstHost = dstHost.decode('utf8')
            elif atyp == b'\x04':
                dstHost = await aioRead(clientR, ReadMode.EXACT, exactLen=16, logHint=f'{logHint} ipv6')
                dstHost = str(ipaddress.ip_address(dstHost))
            else:
                raise MyError(f'RECV ERRATYP={atyp} {logHint}')

            dstPort = await aioRead(clientR, ReadMode.EXACT, exactLen=2, logHint='dstPort')
            dstPort = int.from_bytes(dstPort, 'big')

        logHint = f'{logHint} {dstHost} {dstPort}'
        log.info(f'{logHint} connStart...')

        serverR, serverW = await asyncio.open_connection(args.listenHost, args.listenPort1)
        bindHost, bindPort, *_ = serverW.get_extra_info('sockname')
        log.info(f'{logHint} connSucc bind {bindHost} {bindPort}')

        if 'SOCKS5' == proxyType:
            atyp = b'\x03'
            hostData = None
            try:
                ipAddr = ipaddress.ip_address(bindHost)
                if ipAddr.version == 4:
                    atyp = b'\x01'
                    hostData = struct.pack('!L', int(ipAddr))
                else:
                    atyp = b'\x04'
                    hostData = struct.pack('!16s', ipaddress.v6_int_to_packed(int(ipAddr)))
            except Exception:
                hostData = struct.pack(f'!B{len(bindHost)}s', len(bindHost), bindHost)

            data = struct.pack(f'!ssss{len(hostData)}sH', b'\x05', b'\x00', b'\x00', atyp, hostData, int(bindPort))
            await aioWrite(clientW, data, logHint='reply')
        else:
            data = f"{proto} 200 Connection Established\r\n\r\n".encode()
            await aioWrite(clientW, data, logHint='response')

        await aioWrite(serverW, (dstHost + "\r\n").encode(), logHint='dstHost')
        if type(dstPort) is int:
            dstPort = str(dstPort)
        await aioWrite(serverW, dstPort.encode(), logHint='dstPort')
        await aioWrite(serverW, (args.username + '\r\n').encode(), logHint='username')
        await aioWrite(serverW, (args.password + '\r\n').encode(), logHint='password')

        await asyncio.wait({
            asyncio.create_task(xferDataSend(clientR, serverW, logHint=f'{logHint} fromClient')),
            asyncio.create_task(xferDataRecv(serverR, clientW, logHint=f'{logHint} fromServer'))
        })

    except MyError as exc:
        log.info(f'{logHint} {exc}')
        await aioClose(clientW, logHint=logHint)
        await aioClose(serverW, logHint=logHint)
    except OSError:
        log.info(f'{logHint} connFail')
        await aioClose(clientW, logHint=logHint)
    except Exception as exc:
        log.error(f'{traceback.format_exc()}')
        exit(1)

async def doRemote(clientR, clientW):
    serverR, serverW = None, None
    try:
        clientHost, clientPort, *_ = clientW.get_extra_info('peername')
        logHint = f'{clientHost} {clientPort}'

        dstHost_bytes = await aioRead(clientR, ReadMode.UNTIL, untilSep=b'\r\n', logHint='dstHost')
        dstHost, *_ = dstHost_bytes.decode().split('\r\n')
        dstPort_bytes = await aioRead(clientR, ReadMode.EXACT, exactLen=2, logHint='dstPort')
        dstPort = dstPort_bytes.decode()
        username_bytes = await aioRead(clientR, ReadMode.UNTIL, untilSep=b'\r\n', logHint='username')
        username, *_ = username_bytes.decode().split('\r\n')
        password_bytes = await aioRead(clientR, ReadMode.UNTIL, untilSep=b'\r\n', logHint='password')
        password, *_ = password_bytes.decode().split('\r\n')

        async with aiosqlite3.connect('user.db') as db:
            cursor = await db.execute("select bandwidth from user where name == ? and password == ?", (username, password))
            userdata = await cursor.fetchone()
            bandwidth = userdata[0]
         
        if userdata:
            logHint = f'{logHint} {dstHost} {dstPort}'
            log.info(f'{logHint} connStart...')

            serverR, serverW = await asyncio.open_connection(dstHost, dstPort)
            bindHost, bindPort, *_ = serverW.get_extra_info('sockname')
            log.info(f'{logHint} connSucc bind {bindHost} {bindPort}')

            await asyncio.wait({
                asyncio.create_task(xferData(clientR, serverW, logHint=f'{logHint} fromClient')),
                asyncio.create_task(xferDataTokenBucket(serverR, clientW, bandwidth, logHint=f'{logHint} fromServer'))
            })
        else:
            log.info(f'wrong username/password!')
            await aioClose(clientW, logHint="wrong username/password")

    except MyError as exc:
        log.info(f'{logHint} {exc}')
        await aioClose(clientW, logHint=logHint)
        await aioClose(serverW, logHint=logHint)
    except OSError:
        log.info(f'{logHint} connFail')
        await aioClose(clientW, logHint=logHint)
    except Exception as exc:
        log.error(f'{traceback.format_exc()}')
        exit(1)

async def localTask():
    if args.consolePort:
        ws_server = await websockets.serve(localConsole, '127.0.0.1', args.consolePort)
        log.info(f'CONSOLE LISTEN {ws_server.sockets[0].getsockname()}')

    srv = await asyncio.start_server(doClient, host=args.listenHost, port=args.listenPort)
    addrList = list([s.getsockname() for s in srv.sockets])
    log.info(f'LISTEN {addrList}')
    async with srv:
        await srv.serve_forever()

async def remoteTask():
    srv = await asyncio.start_server(doRemote, host=args.listenHost, port=args.listenPort1)
    addrList = list([s.getsockname() for s in srv.sockets])
    log.info(f'LISTEN {addrList}')
    async with srv:
        await srv.serve_forever()

async def xferData(srcR, dstW, *, logHint=None):
    try:
        while True:
            data = await aioRead(srcR, ReadMode.MAX, maxLen=65535, logHint='')
            await aioWrite(dstW, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(dstW, logHint=logHint)

async def aioClose(w, *, logHint=None):
    if not w:
        await asyncio.sleep(0.001)
        return
    host, port, *_ = w.get_extra_info('peername')
    log.info(f'{logHint} close... peer {host} {port}')
    try:
        w.close()
        await w.wait_closed()
    except Exception as exc:
        pass

async def aioRead(r, mode, *, logHint=None, exactData=None, exactLen=None, maxLen=-1, untilSep=b'\r\n'):
    data = None
    try:
        if ReadMode.EXACT == mode:
            exactLen = len(exactData) if exactData else exactLen
            data = await r.readexactly(exactLen)
            if exactData and data != exactData:
                raise MyError(f'recvERR={data} {logHint}')
        elif ReadMode.LINE == mode:
            data = await r.readline()
        elif ReadMode.MAX == mode:
            data = await r.read(maxLen)
        elif ReadMode.UNTIL == mode:
            data = await r.readuntil(untilSep)
        else:
            log.error(f'INVALID mode={mode}')
            exit(1)
    except ConnectionResetError as exc:
        raise MyError(f'recvEXC={exc} {logHint}')
    except ConnectionAbortedError as exc:
        raise MyError(f'recvEXC={exc} {logHint}')
    if not data:
        raise MyError(f'recvEOF {logHint}')
    return data

async def aioWrite(w, data, *, logHint=''):
    try:
        w.write(data)
        await w.drain()
    except ConnectionAbortedError as exc:
        raise MyError(f'sendEXC={exc} {logHint}')

async def main():
    if args.username:
        asyncio.create_task(localTask())
    else:
        asyncio.create_task(remoteTask())

    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)

    _parser = argparse.ArgumentParser(description='socks5 https dual proxy server')
    _parser.add_argument('--host', dest='listenHost', default='127.0.0.1', metavar='listen_host', help='proxy listen host')
    _parser.add_argument('--localport', dest='listenPort', default=1081, metavar='listen_port', help='local proxy listen port')
    _parser.add_argument('--remoteport', dest='listenPort1', default=1082, metavar='listen_port1', help='remote proxy listen port')
    _parser.add_argument('--username', dest='username', metavar='user_name', help='local proxy username')
    _parser.add_argument('--password', dest='password', metavar='pass_word', help='local proxy password')
    _parser.add_argument('--consoleport', dest='consolePort', default=1083, metavar='console_port', help='local gui listen port')

    args = _parser.parse_args()

    if sys.platform == 'win32':
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    asyncio.run(main())
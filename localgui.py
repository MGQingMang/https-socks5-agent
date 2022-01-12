import sys
import logging
import websockets
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtNetwork import *
from PyQt5.QtWidgets import *
from PyQt5.QtWebSockets import *

class Window(QDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)

        layout=QVBoxLayout()

        self.startBtn = QPushButton('Start')
        self.startBtn.clicked.connect(self.startClicked)
        self.listenPortLabel = QLabel("localPort:")
        self.listenPortLine = QLineEdit()
        self.usernameLabel = QLabel("username:")
        self.usernameLine = QLineEdit()
        self.passwordLabel = QLabel("password:")
        self.passwordLine = QLineEdit()
        self.consolePortLabel = QLabel("consolePort:")
        self.consolePortLine = QLineEdit()
        self.remoteHostLabel = QLabel("Host:")
        self.remoteHostLine = QLineEdit()
        self.remotePortLabel = QLabel("remotePort:")
        self.remotePortLine = QLineEdit()
        self.sendBandwidthLabel = QLabel("sendBandwidth:")
        self.sendBandwidthLine = QLabel()
        self.recvBandwidthLabel = QLabel("recvBandwidth:")
        self.recvBandwidthLine = QLabel()

        layout.addWidget(self.remoteHostLabel)
        layout.addWidget(self.remoteHostLine)
        layout.addWidget(self.listenPortLabel)
        layout.addWidget(self.listenPortLine)
        layout.addWidget(self.remotePortLabel)
        layout.addWidget(self.remotePortLine)
        layout.addWidget(self.consolePortLabel)
        layout.addWidget(self.consolePortLine)
        layout.addWidget(self.usernameLabel)
        layout.addWidget(self.usernameLine)
        layout.addWidget(self.passwordLabel)
        layout.addWidget(self.passwordLine)
        layout.addWidget(self.startBtn)
        layout.addWidget(self.sendBandwidthLabel)
        layout.addWidget(self.sendBandwidthLine)
        layout.addWidget(self.recvBandwidthLabel)
        layout.addWidget(self.recvBandwidthLine)
        
        
        self.passwordLine.setEchoMode(QLineEdit.Password)

        self.remoteHostLine.setText("127.0.0.1")
        self.listenPortLine.setText("1081")
        self.remotePortLine.setText("1082")
        self.consolePortLine.setText("1083")       
        
        self.setLayout(layout)
     
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.finished.connect(self.processFinished)
        self.process.started.connect(self.processStarted)
        self.process.readyReadStandardOutput.connect(self.processReadyRead)

    def processReadyRead(self):
        data = self.process.readAll()
        try:
            msg = data.data().decode().strip()
            log.debug(f'msg={msg}')
        except Exception as exc:
            log.error(f'{traceback.format_exc()}')
            exit(1)
        
    def processStarted(self):
        process = self.sender()
        processId = process.processId()
        log.debug(f'pid={processId}')
        self.startBtn.setText('Stop')

        self.websocket = QWebSocket()
        self.websocket.connected.connect(self.websocketConnected)
        self.websocket.disconnected.connect(self.websocketDisconnected)
        self.websocket.textMessageReceived.connect(self.websocketMsgRcvd)
        self.websocket.open(QUrl(f'ws://127.0.0.1:{self.consolePortLine.text()}/'))

    def startClicked(self):
        btn = self.sender()
        text = btn.text().lower()
        if text.startswith('start'):
            listenPort = self.listenPortLine.text()
            username = self.usernameLine.text()
            password = self.passwordLine.text()
            consolePort = self.consolePortLine.text()
            remoteHost = self.remoteHostLine.text()
            remotePort = self.remotePortLine.text()
            cmdLine = f'python local_remote.py --localport {listenPort} --username {username} --password {password} --consoleport {consolePort} --host {remoteHost} --remoteport {remotePort}'
            log.debug(f'cmd={cmdLine}')
            self.process.start(cmdLine)
        else:
            self.process.kill()

    def websocketConnected(self):
        self.websocket.sendTextMessage('secret')

    def websocketDisconnected(self):
        self.process.kill()

    def websocketMsgRcvd(self, msg):
        log.debug(f'msg={msg}')
        sendBandwidth, recvBandwidth, *_ = msg.split()
        nowTime = QDateTime.currentDateTime().toString('hh:mm:ss')
        self.sendBandwidthLine.setText(f'{nowTime} {str(int(sendBandwidth))} Bytes/s')
        self.recvBandwidthLine.setText(f'{nowTime} {str(int(recvBandwidth))} Bytes/s')
    def processFinished(self):
        pass

def main():
    app = QApplication(sys.argv)

    w = Window()
    w.show()
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)

    main()
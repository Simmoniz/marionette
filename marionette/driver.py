#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
import socket
import struct

import fte.bit_ops

import marionette.action
import marionette.channel
import marionette.conf
import marionette.dsl
import marionette.PA


SERVER_IFACE = marionette.conf.get("server.listen_iface")
SERVER_TIMEOUT = 0.001


class Driver(object):
    def __init__(self, party):
        self.clean_executeables_ = []
        self.executeables_ = []
        self.party_ = party
        self.multiplexer_outgoing_ = None
        self.multiplexer_incoming_ = None
        self.tcp_socket_map_ = {}

    def execute(self):
        if self.party_ == "server":
            for executable in self.clean_executeables_:
                channel = self.acceptNewChannel(executable)
                if channel:
                    new_executable = executable.replicate()
                    new_executable.set_channel(channel)
                    self.executeables_.append(new_executable)
                    new_executable.start()
        elif self.party_ == "client":
            for executable in self.executeables_:
                if not executable.get_channel():
                    channel = self.openNewChannel(executable)
                    executable.set_channel(channel)
                    executable.start()

        executables_ = []
        for executable in self.executeables_:
            if executable.isRunning():
                executables_.append(executable)
            else:
                channel = executable.get_channel()
                if channel:
                    channel.close()
        self.executeables_ = executables_

    def one_execution_cycle(self, n=1):
        not_opened = []
        self.executeables_ = []
        for executable in self.clean_executeables_:
            for i in range(n):
                new_executable = executable.replicate()
                self.executeables_ += [new_executable]
                not_opened += [new_executable]

        while len(self.executeables_) > 0:
            ###
            if self.party_ == "server":
                if len(not_opened):
                    executable = not_opened[0]
                    channel = self.acceptNewChannel(executable)
                    if channel:
                        executable.set_channel(channel)
                        not_opened.pop(0)
                        executable.start()
            elif self.party_ == "client":
                if len(not_opened):
                    executable = not_opened[0]
                    channel = self.openNewChannel(executable)
                    if channel:
                        executable.set_channel(channel)
                        not_opened.pop(0)
                        executable.start()
                ###

            executables_ = []
            for executable in self.executeables_:
                if executable.isRunning():
                    executables_.append(executable)
                else:
                    channel = executable.get_channel()
                    channel.close()
            self.executeables_ = executables_

    def acceptNewChannel(self, executable):
        port = executable.get_port()

        if not port: return None

        if not self.tcp_socket_map_.get(port):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                         struct.pack('ii', 0, 0))
            s.bind((SERVER_IFACE, int(port)))
            s.listen(5)
            s.settimeout(SERVER_TIMEOUT)
            self.tcp_socket_map_[port] = s

        try:
            conn, addr = self.tcp_socket_map_[port].accept()
            channel = marionette.channel.new(conn)
        except socket.timeout:
            channel = None

        return channel

    def openNewChannel(self, executable):
        port = executable.get_port()

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((SERVER_IFACE, int(port)))
            channel = marionette.channel.new(s)
        except Exception as e:
            channel = None

        return channel

    def stop(self):
        while len(self.executeables_) > 0:
            executable = self.executeables_.pop(0)
            executable.stop()

    def isRunning(self):
        return len(self.executeables_) > 0

    def setFormat(self, format_name):
        with open("marionette/formats/" + format_name + ".mar") as f:
            mar_str = f.read()

        settings = marionette.dsl.loads(mar_str)

        first_sender = 'client'
        if format_name in ["ftp_pasv_transfer"]:
            first_sender = "server"

        executable = marionette.PA.PA(self.party_, first_sender)
        executable.set_transport(settings.getTransport())
        executable.set_port(settings.getPort())
        executable.local_args_["model_uuid"] = get_model_uuid(mar_str)
        for transition in settings.getTransitions():
            executable.add_state(transition[0])
            executable.add_state(transition[1])
            executable.states_[transition[0]].add_transition(transition[1],
                                                             transition[2],
                                                             transition[3])
        executable.actions_ = settings.get_actions()
        executable.set_multiplexer_outgoing(self.multiplexer_outgoing_)
        executable.set_multiplexer_incoming(self.multiplexer_incoming_)

        if executable.states_.get("end"):
            executable.add_state("dead")
            executable.states_["end"].add_transition("dead", 'NULL', 1)
            executable.states_["dead"].add_transition("dead", 'NULL', 1)

        executable.build_cache()

        self.clean_executeables_ += [executable]
        if self.party_ == "client":
            self.executeables_ += [executable.replicate()]

    def set_multiplexer_outgoing(self, multiplexer):
        self.multiplexer_outgoing_ = multiplexer

    def set_multiplexer_incoming(self, multiplexer):
        self.multiplexer_incoming_ = multiplexer

    def reset(self):
        self.executeables_ = []
        if self.party_ == "client":
            for executable in self.clean_executeables_:
                self.executeables_ += [executable.replicate()]


def get_model_uuid(format_str):
    m = hashlib.md5()
    m.update(format_str)
    bytes = m.digest()
    return fte.bit_ops.bytes_to_long(bytes[:4])

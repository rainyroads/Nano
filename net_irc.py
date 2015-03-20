# !/usr/bin/env python3
"""
net_irc.py: Establish a new IRC connection
"""
import re
import shlex
import logging
from ast import literal_eval
from html.parser import unescape
from configparser import ConfigParser
import irc.bot
import irc.strings
import irc.events
from modules import Commander
from language import Language
from logger import IRCChannelLogger, IRCQueryLogger, IRCLoggerSource

__author__     = "Makoto Fujikawa"
__copyright__  = "Copyright 2015, Makoto Fujikawa"
__version__    = "1.0.0"
__maintainer__ = "Makoto Fujikawa"


class NanoIRC(irc.bot.SingleServerIRCBot):
    """
    Establishes a new connection to the configured IRC server
    """

    def __init__(self, network, channel):
        """
        Initialize a new Nano IRC instance

        Args:
            channel(str):  The channel to join
            nickname(str): The nick to use
            server(str):   The server to connect to
            port(int):     The server port number
        """
        irc.bot.SingleServerIRCBot.__init__(self, [(network.host, network.port)], network.nick, network.nick)
        # Load our configuration

        # Setup
        self.network = network
        self.channel = channel
        self.lang = Language()
        self.command = Commander()
        self.log = logging.getLogger('nano.irc')

        # Network feature list
        self.network_features = {}

        # Set up our channel and query loggers
        self.channel_logger = IRCChannelLogger(self, IRCLoggerSource(channel.name), bool(self.channel.log))
        self.query_loggers  = {}

        # Patterns
        self.command_pattern = re.compile("^>>>( )?[a-zA-Z]+")
        self.response_pattern = re.compile("{'(.+)':\s?'(.+)'}")

    @staticmethod
    def config(network=None):
        """
        Static method that returns the logger configuration

        Returns:
            ConfigParser
        """
        config = ConfigParser()
        config.read('config/irc.cfg')

        if network:
            return config[network]

        return config

    def _execute_command(self, command_string, source, public=True):
        """
        Execute an IRC command
        """
        self.log.info('Executing command ' + command_string[0])

        # Attempt to execute the command
        try:
            reply = self.command.execute(command_string, self, source, public)
            return reply
        except Exception as e:
            self.log.warn('Exception thrown when executing command "{cmd}": {exception}'
                          .format(cmd=command_string[0], exception=str(e)))
            return

    def _parse_message(self, message):
        """
        Replace accepted HTML formatting with control codes and strip any excess HTML that remains

        Args:
            message(str): The message to parse

        Returns:
            str: The IRC formatted string
        """
        message = str(message)
        self.log.debug('Parsing message response: ' + message)

        # Parse bold text
        message = re.sub("(<strong>|<\/strong>)", "\x02", message, 0, re.UNICODE)

        # Strip any HTML formatting IRC protocol does not support
        message = re.sub('<[^<]+?>', '', message)

        # Unescape any HTML entities
        message = unescape(message)

        self.log.debug('Returning parsed message: ' + message)
        return message

    def _deliver_messages(self, messages, source, channel, public=True):
        # Make sure we have a list of messages to iterate through
        if not isinstance(messages, list):
            messages = [messages]

        # Are we returning to a public channel or query by default?
        if not public:
            default_destination = source.nick
        else:
            default_destination = channel.name

        # Iterate through our messages
        for message in messages:
            if isinstance(message, dict):
                # Split our destination and parse our message
                destination, message = message.popitem()

                # Call a requested command and loop back our response
                if destination == "command":
                    reply = self._execute_command(message, source, public)
                    return self._deliver_messages(reply, source.nick, channel.name)

                message = self._parse_message(message)

                # Where are we sending the message?
                if destination == "private":
                    # Query message
                    self.log.info('Sending query to ' + source.nick)
                    self.connection.privmsg(source.nick, message)
                elif destination == "private_notice":
                    # Query notice
                    self.log.info('Sending private notice to ' + source.nick)
                    self.connection.notice(source.nick, message)
                elif destination == "private_action":
                    # Query action
                    self.log.info('Sending query action to ' + source.nick)
                    self.connection.action(source.nick, message)
                elif destination == "public_action":
                    # Channel action
                    self.channel_logger.log(self.channel_logger.ACTION, self.connection.get_nickname(), message=message)
                    self.log.info('Sending action to ' + channel.name)
                    self.connection.action(channel.name, message)
                elif destination == "public_notice":
                    # Channel notice
                    self.channel_logger.log(self.channel_logger.NOTICE, self.connection.get_nickname(), message=message)
                    self.log.info('Sending notice to ' + channel.name)
                    self.connection.notice(channel.name, message)
                elif destination == "public":
                    # Channel message
                    self.channel_logger.log(self.channel_logger.MESSAGE, self.connection.get_nickname(),
                                            message=message)
                    self.log.info('Sending message to ' + channel.name)
                    self.connection.privmsg(channel.name, message)
                elif destination == "action":
                    # Default action
                    if public:
                        self.channel_logger.log(self.channel_logger.ACTION, self.connection.get_nickname(),
                                                message=message)

                    self.log.info('Sending action to ' + channel.name)
                    self.connection.action(default_destination, message)
                else:
                    # Default message
                    if public:
                        self.channel_logger.log(self.channel_logger.MESSAGE, self.connection.get_nickname(),
                                                message=message)

                    self.log.info('Sending message to ' + default_destination)
                    self.connection.privmsg(default_destination, message)
            else:
                # Default message
                message = self._parse_message(message)
                if public:
                    self.channel_logger.log(self.channel_logger.MESSAGE, self.connection.get_nickname(),
                                            message=message)

                self.log.info('Sending message to ' + default_destination)
                self.connection.privmsg(default_destination, message)

    def query_logger(self, source):
        """
        Retrieve a query logger instance for the specified client

        Args:
            source(irc.client.NickMask): NickMask of the client

        Returns:
            logger.IRCQueryLogger
        """
        # Do we already have a query logging instance for this user?
        if source.nick in self.query_loggers:
            return self.query_loggers[source.nick]

        # Set up a new query logger instance
        self.query_loggers[source.nick] = IRCQueryLogger(self, IRCLoggerSource(source.nick, source.host))
        return self.query_loggers[source.nick]

    ################################
    # Numeric / Response Events    #
    ################################

    def on_nicknameinuse(self, c, e):
        """
        Attempt to regain access to a nick in use if we can, otherwise append an underscore and retry

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # TODO: Ghost using nickserv if possible
        nick = c.get_nickname() + "_"
        self.log.info('Nickname {nick} in use, retrying with {new_nick}'.format(nick=c.get_nickname(), new_nick=nick))
        c.nick(nick)

    def on_serviceinfo(self, c, e):
        """
        ???

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_welcome(self, c, e):
        """
        Join our specified channels once we get a welcome to the server

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # TODO: Multi-channel support
        self.log.info('Joining channel: ' + self.channel.name)
        c.join(self.channel.name)

    def on_featurelist(self, c, e):
        """
        Parse and save the servers supported IRC features for later reference

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # TODO
        # feature_pattern = re.compile("^([A-Z]+)(=(\S+))?$")
        pass

    def on_cannotsendtochan(self, c, e):
        """
        Handle instances where we cannot send a message to a channel we are in (generally when we are banned)

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_toomanychannels(self, c, e):
        """
        Handle instances where we attempt to join more channels than the server allows

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_erroneusnickname(self, c, e):
        """
        Handle instances where the nickname we want to use is considered erroneous by the server

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_unavailresource(self, c, e):
        """
        Handle instances where the nickname we want to use is not in use but unavailable (Release from nickserv?)

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # Release nick from nickserv
        pass

    def on_channelisfull(self, c, e):
        """
        If we try and join a channel that is full, wait before attempting to join the channel again

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # Wait XX seconds and attempt to join
        pass

    def on_keyset(self, c, e):
        """
        Handle instances where we try and join a channel that is key protected (and we don't have a key saved)

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_badchannelkey(self, c, e):
        """
        Handle instances where our key for a channel is returned invalid

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_inviteonlychan(self, c, e):
        """
        If we attempt to join a channel that is invite only, see if we can knock to request access

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # Knock knock
        pass

    def on_bannedfromchan(self, c, e):
        """
        Handle instances where we are banned from a channel we are trying to join

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_banlistfull(self, c, e):
        """
        Handle instances where we are unable to ban a user because the channels banlist is full

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    def on_chanoprivsneeded(self, c, e):
        """
        Handle instances where we attempt to perform an action that requires channel operate privileges

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass

    ################################
    # Protocol Events              #
    ################################

    def on_pubmsg(self, c, e):
        """
        Handle public channel messages

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # Log the message
        self.channel_logger.log(self.channel_logger.MESSAGE, e.source.nick, e.source.host, e.arguments[0])

        # Get our hostmask to use as our name
        source = str(e.source).split("@", 1)
        self.lang.set_name(source[1], e.source.nick)

        # Are we trying to call a command directly?
        if self.command_pattern.match(e.arguments[0]):
            self.log.info('Acknowledging public command request from ' + e.source.nick)
            reply = self._execute_command(e.arguments[0], e.source, True)
        else:
            self.log.debug('Querying language engine for a response to ' + e.source.nick)
            raw_reply = self.lang.get_reply(source[1], e.arguments[0])
            try:
                reply = literal_eval(raw_reply)
            except (SyntaxError, ValueError) as exception:
                self.log.debug('Anticipated exception caught when requesting the response: ' + str(exception))
                reply = raw_reply

        if reply:
            self.log.debug('Delivering response messages')
            self._deliver_messages(reply, e.source, self.channel)
        else:
            self.log.debug('No response received')

    def on_action(self, c, e):
        """
        Handle actions (from both public channels AND queries)

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # Log the action
        if e.target == c.get_nickname():
            logger = self.query_logger(e.source)
            logger.log(logger.ACTION, IRCLoggerSource(e.source.nick, e.source.host), e.arguments[0])
        else:
            self.channel_logger.log(self.channel_logger.ACTION, e.source.nick, e.source.host, e.arguments[0])

    def on_pubnotice(self, c, e):
        """
        Handle public channel notices

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        self.channel_logger.log(self.channel_logger.NOTICE, e.source.nick, e.source.host, e.arguments[0])

    def on_privmsg(self, c, e):
        """
        Handle private messages (queries)

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # Log the message
        logger = self.query_logger(e.source)
        logger.log(logger.MESSAGE, IRCLoggerSource(e.source.nick, e.source.host), e.arguments[0])

        # Get our hostmask to use as our name
        source = str(e.source).split("@", 1)
        self.lang.set_name(source[1], e.source.nick)

        # Are we trying to call a command directly?
        if self.command_pattern.match(e.arguments[0]):
            self.log.info('Acknowledging private command request from ' + e.source.nick)
            reply = self._execute_command(e.arguments[0], e.source, False)
        else:
            self.log.debug('Querying language engine for a response to ' + e.source.nick)
            raw_reply = self.lang.get_reply(source[1], e.arguments[0])
            try:
                reply = literal_eval(raw_reply)
            except (SyntaxError, ValueError) as exception:
                self.log.debug('Anticipated exception caught when requesting the response: ' + str(exception))
                reply = raw_reply

        if reply:
            self.log.debug('Delivering response messages')
            self._deliver_messages(reply, e.source, self.channel, False)
        else:
            self.log.info(e.source.nick + ' sent me a query I didn\'t know how to respond to')

    def on_privnotice(self, c, e):
        """
        Handle private notices

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # Log the notice
        logger = self.query_logger(e.source)
        logger.log(logger.NOTICE, IRCLoggerSource(e.source.nick, e.source.host), e.arguments[0])

    def on_join(self, c, e):
        """
        Handle user join events

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        self.channel_logger.log(self.channel_logger.JOIN, e.source.nick, e.source.host)

    def on_part(self, c, e):
        """
        Handle user part events

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        if not len(e.arguments):
            e.arguments.append(None)

        self.channel_logger.log(self.channel_logger.PART, e.source.nick, e.source.host, e.arguments[0])

    def on_quit(self, c, e):
        """
        Handle channel exits

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        # TODO: Clear login sessions
        if not len(e.arguments):
            e.arguments.append(None)

        self.channel_logger.log(self.channel_logger.QUIT, e.source.nick, e.source.host, e.arguments[0])

    def on_kick(self, c, e):
        """
        Handle channel kick events

        Args:
            c(irc.client.ServerConnection): The active IRC server connection
            e(irc.client.Event): The event response data
        """
        pass


class IRCFeatureList:
    def __init__(self):
        pass
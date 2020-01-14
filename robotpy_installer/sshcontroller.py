import configparser
import logging
import re
from os.path import exists, join, expanduser

import paramiko

from robotpy_installer.errors import SshExecError, Error
from robotpy_installer.robotfinder import RobotFinder
from robotpy_installer.utils import _resolve_addr

logger = logging.getLogger("robotpy.installer")


class SuppressKeyPolicy(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        return


class SshController(object):
    """
        Use this to execute commands on a roboRIO in a
        cross platform manner
    """

    def __init__(self, hostname, username, password):
        self.username = username
        self.password = password
        self.hostname = hostname

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(SuppressKeyPolicy)

    def ssh_connect(self):
        self.client.connect(
            self.hostname, username=self.username, password=self.password, port=22
        )

    def ssh_close_connection(self):
        self.client.close()

    def ssh_exec_commands(self, commands, existing_connection=False):

        if not existing_connection:
            self.ssh_connect()

        _, stdout, _ = self.client.exec_command(commands)

        for line in iter(stdout.readline, ""):
            print(line, end="")

        retval = stdout.channel.recv_exit_status()

        if retval != 0:
            raise SshExecError(
                "Command %s returned non-zero error status %s" % (commands, retval),
                retval,
            )

        if not existing_connection:
            self.ssh_close_connection()


def ssh_from_cfg(cfg_filename, username, password, hostname=None, no_resolve=False):
    # hostname can be a team number or an ip / hostname

    dirty = True
    cfg = configparser.ConfigParser()
    cfg.setdefault("auth", {})

    if exists(cfg_filename):
        cfg.read(cfg_filename)
        dirty = False

    if hostname is not None:
        dirty = True
        cfg["auth"]["hostname"] = str(hostname)

    hostname = cfg["auth"].get("hostname")

    if not hostname:
        dirty = True

        print("Robot setup (hit enter for default value):")
        while not hostname:
            hostname = input("Team number or robot hostname: ")

        cfg["auth"]["hostname"] = hostname

    if dirty:
        with open(cfg_filename, "w") as fp:
            cfg.write(fp)

    # see if an ssh alias exists
    try:
        with open(join(expanduser("~"), ".ssh", "config")) as fp:
            hn = hostname.lower()
            for line in fp:
                if re.match(r"\s*host\s+%s\s*" % hn, line.lower()):
                    no_resolve = True
                    break
    except Exception:
        pass

    # check to see if this is a team number
    team = None
    try:
        team = int(hostname.strip())
    except ValueError:
        # check to see if it matches a team hostname
        # -> allows legacy hostname configurations to benefit from
        #    the robot finder
        if not no_resolve:
            hostmod = hostname.lower().strip()
            m = re.search(r"10.(\d+).(\d+).2", hostmod)
            if m:
                team = int(m.group(1)) * 100 + int(m.group(2))
            else:
                m = re.match(r"roborio-(\d+)-frc(?:\.(?:local|lan))?$", hostmod)
                if m:
                    team = int(m.group(1))

    if team:
        logger.info("Finding robot for team %s", team)
        finder = RobotFinder(
            ("10.%d.%d.2" % (team // 100, team % 100), False),
            ("roboRIO-%d-FRC.local" % team, True),
            ("172.22.11.2", False),  # USB
            ("roboRIO-%d-FRC" % team, True),  # default DNS
            ("roboRIO-%d-FRC.lan" % team, True),
            ("roboRIO-%d-FRC.frc-field.local" % team, True),  # practice field mDNS
        )
        hostname = finder.find()
        no_resolve = True
        if not hostname:
            raise Error("Could not find team %s robot" % team)

    if not no_resolve:
        hostname = _resolve_addr(hostname)

    logger.info("Connecting to robot via SSH at %s", hostname)

    return SshController(hostname, username, password)
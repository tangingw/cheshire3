"""Register a Cheshire3 Database config file.

Register a configuration file for a Cheshire3 Database with the server.

This process simply tells the server that it should include the
configuration(s) in your file (it does not ingest your file) so you
don't need to re-register when you make changes to the file.
"""

from __future__ import with_statement

import sys
import os

from lxml import etree
from lxml.builder import ElementMaker

from cheshire3.server import SimpleServer
from cheshire3.session import Session
from cheshire3.internal import cheshire3Root, CONFIG_NS
from cheshire3.bootstrap import BSLxmlParser, BootstrapDocument
from cheshire3.exceptions import ObjectDoesNotExistException
from cheshire3.exceptions import ConfigFileException
from cheshire3.exceptions import PermissionException
from cheshire3.commands.cmd_utils import Cheshire3ArgumentParser


def main(argv=None):
    """Register a Database configuration file with the Cheshire3 Server."""
    global argparser, session, server
    if argv is None:
        args = argparser.parse_args()
    else:
        args = argparser.parse_args(argv)
    session = Session()
    server = SimpleServer(session, args.serverconfig)
    # Make path to configfile absolute
    args.configfile = os.path.abspath(os.path.expanduser(args.configfile))
    # Read in proposed config file
    with open(args.configfile, 'r') as fh:
        confdoc = BootstrapDocument(fh)
        # Check it's parsable
        try:
            confrec = BSLxmlParser.process_document(session, confdoc)
        except etree.XMLSyntaxError as e:
            msg = ("Config file {0} is not well-formed and valid XML: "
                   "{1}".format(args.configfile, e.message))
            server.log_critical(session, msg)
            raise ConfigFileException(msg)
    # Extract the database identifier
    confdom = confrec.get_dom(session)
    dbid = confdom.attrib.get('id', None)
    if dbid is None:
        msg = ("Config file {0} must have an 'id' attribute at the top-level"
               "".format(args.configfile))
        server.log_critical(session, msg)
        raise ConfigFileException(msg)
    # Check that the identifier is not already in use by an existing database
    try:
        server.get_object(session, dbid)
    except ObjectDoesNotExistException:
        # Doesn't exists, so OK to init it
        pass
    else:
        # TODO: check for --force ?
        msg = ("Database with id '{0}' is already registered. "
               "Please specify a different id in your configurations "
               "file.".format(dbid))
        server.log_critical(session, msg)
        raise ConfigFileException(msg)
    
    # Generate plugin XML
    plugin = E.config(
                     E.subConfigs(
                         E.path({'type': "database", 'id': dbid},
                                args.configfile
                         )
                     )
                 )
    # Try to do this by writing config plugin file if possible
    serverDefaultPath = server.get_path(session,
                                        'defaultPath',
                                        cheshire3Root)
    userSpecificPath = os.path.join(os.path.expanduser('~'),
                                    '.cheshire3-server')
    pluginPath = os.path.join('configs',
                              'databases',
                              '{0}.xml'.format(dbid))
    try:
        pluginfh = open(os.path.join(serverDefaultPath, pluginPath), 'w')
    except IOError:
        try:
            pluginfh = open(os.path.join(userSpecificPath, pluginPath), 'w')
        except IOError:
            msg = ("Database plugin directory {0} unavailable for writing"
                   "".format(os.path.join(userSpecificPath, pluginPath)))
            server.log_critical(session, msg)
            raise PermissionException(msg)
    pluginfh.write(etree.tostring(plugin,
                            pretty_print=True,
                            encoding="utf-8"))
    pluginfh.close()
    server.log_info(session,
                    "Database configured in {0} registered with Cheshire3 "
                    "Server configured in {1}".format(args.configfile,
                                                      args.serverconfig))
    return 0
        

argparser = Cheshire3ArgumentParser(conflict_handler='resolve',
                                    description=__doc__.splitlines()[0])

argparser.add_argument('configfile', type=str,
                       action='store', nargs='?',
                       default=os.path.join(os.getcwd(), 'config.xml'),
                       metavar='CONFIGFILE',
                       help=("path to configuration file for the database to "
                             "register with the Cheshire3 server. Default: "
                             "config.xml"))

# Set up ElementMaker for Cheshire3 config namespace
E = ElementMaker(namespace=CONFIG_NS, nsmap={None: CONFIG_NS})

session = None
server = None

if __name__ == '__main__':
    sys.exit(main())

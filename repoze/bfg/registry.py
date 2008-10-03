import os
import sys
import threading

import zope.component

from zope.component import getGlobalSiteManager
from zope.component.interfaces import ComponentLookupError
from zope.component.interfaces import IComponentLookup
from zope.component.registry import Components
from zope.component import getSiteManager as original_getSiteManager

from zope.interface import implements

from repoze.bfg.interfaces import ISettings
from repoze.bfg.interfaces import ILogger
from repoze.bfg.zcml import zcml_configure
from repoze.bfg.log import make_stream_logger

class ThreadLocalRegistryManager(threading.local):
    registry = getGlobalSiteManager()
    def set(self, registry):
        self.registry = registry

    def get(self):
        return self.registry

    def clear(self):
        self.registry = getGlobalSiteManager()

registry_manager = ThreadLocalRegistryManager()

def setRegistryManager(manager): # for unit tests
    global registry_manager
    old_registry_manager = registry_manager
    registry_manager = manager
    return old_registry_manager

def makeRegistry(filename, package, options=None, lock=threading.Lock()):
    # We push our ZCML-defined configuration into an app-local
    # component registry in order to allow more than one bfg app to
    # live in the same process space without one unnecessarily
    # stomping on the other's component registrations (although I
    # suspect directives that have side effects are going to fail).
    # The only way to do that currently is to override
    # zope.component.getGlobalSiteManager for the duration of the ZCML
    # includes.  We acquire a lock in case another make_app runs in a
    # different thread simultaneously, in a vain attempt to prevent
    # mixing of registrations.  There's not much we can do about
    # non-make_app code that tries to use the global site manager API
    # directly in a different thread while we hold the lock.  Those
    # registrations will end up in our application's registry.
    lock.acquire()
    try:
        registry = Components(package.__name__)
        registry_manager.set(registry)
        if options is None:
            options = {}
        settings = Settings(options)
        registry.registerUtility(settings, ISettings)
        if options.get('debug_authorization'):
            auth_logger = make_stream_logger('repoze.bfg.authdebug',sys.stderr)
            registry.registerUtility(auth_logger, ILogger,
                                     'repoze.bfg.authdebug')
        original_getSiteManager.sethook(getSiteManager)
        zope.component.getGlobalSiteManager = registry_manager.get
        zcml_configure(filename, package=package)
        return registry
    finally:
        zope.component.getGlobalSiteManager = getGlobalSiteManager
        lock.release()
        registry_manager.clear()

class Settings(object):
    implements(ISettings)
    reload_templates = False
    def __init__(self, options):
        self.__dict__.update(options)

def getSiteManager(context=None):
    if context is None:
        return registry_manager.get()
    else:
        try:
            return IComponentLookup(context)
        except TypeError, error:
            raise ComponentLookupError(*error.args)

def asbool(s):
    s = str(s).strip()
    return s.lower() in ('t', 'true', 'y', 'yes', 'on', '1')

def get_options(kw, environ=os.environ):
    # environ is passed in for unit tests
    eget = environ.get
    config_debug_auth = kw.get('debug_authorization', '')
    effective_debug_auth = asbool(eget('BFG_DEBUG_AUTHORIZATION',
                                       config_debug_auth))
    config_reload_templates = kw.get('reload_templates')
    effective_reload_templates = asbool(eget('BFG_RELOAD_TEMPLATES',
                                        config_reload_templates))
    return {
        'debug_authorization': effective_debug_auth,
        'reload_templates':effective_reload_templates,
        }

from zope.testing.cleanup import addCleanUp
try:
    addCleanUp(original_getSiteManager.reset)
except AttributeError:
    # zope.hookable not yet installed
    pass
addCleanUp(registry_manager.clear)

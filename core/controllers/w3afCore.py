'''
w3afCore.py

Copyright 2006 Andres Riancho

This file is part of w3af, http://w3af.org/ .

w3af is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation version 2 of the License.

w3af is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with w3af; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

'''
import os
import sys
import time
import traceback

import core.controllers.output_manager as om
import core.data.kb.config as cf

from core.controllers.core_helpers.progress import progress
from core.controllers.core_helpers.status import w3af_core_status
from core.controllers.core_helpers.profiles import w3af_core_profiles
from core.controllers.core_helpers.plugins import w3af_core_plugins
from core.controllers.core_helpers.target import w3af_core_target
from core.controllers.core_helpers.strategy import w3af_core_strategy
from core.controllers.core_helpers.fingerprint_404 import fingerprint_404_singleton
from core.controllers.core_helpers.exception_handler import ExceptionHandler
from core.controllers.threads.threadpool import Pool

from core.controllers.misc.epoch_to_string import epoch_to_string
from core.controllers.misc.dns_cache import enable_dns_cache
from core.controllers.misc.number_generator import consecutive_number_generator
from core.controllers.misc.homeDir import (create_home_dir,
                                           verify_dir_has_perm, HOME_DIR)
from core.controllers.misc.temp_dir import (create_temp_dir, remove_temp_dir,
                                            TEMP_DIR)
from core.controllers.exceptions import (w3afException, w3afMustStopException,
                                         w3afMustStopByUnknownReasonExc,
                                         w3afMustStopByUserRequest)

from core.data.url.extended_urllib import ExtendedUrllib
from core.data.kb.knowledge_base import kb


class w3afCore(object):
    '''
    This is the core of the framework, it calls all plugins, handles exceptions,
    coordinates all the work, creates threads, etc.

    @author: Andres Riancho (andres.riancho@gmail.com)
    '''
    
    WORKER_THREADS = 20
    
    def __init__(self):
        '''
        Init some variables and files.
        Create the URI opener.
        '''
        # Create some directories, do this every time before starting a new
        # scan and before doing any other core init because these are widely
        # used
        self._home_directory()
        self._tmp_directory()
        
        # We want to have only one exception handler instance during the whole
        # w3af process. The data captured by it will be cleared before starting
        # each scan, but we want to keep the same instance after a scan because
        # we'll extract info from it.
        self.exception_handler = ExceptionHandler()
        
        # These are some of the most important moving parts in the w3afCore
        # they basically handle every aspect of the w3af framework. I create
        # these here because they are used by the UIs even before starting a
        # scan.
        self.profiles = w3af_core_profiles(self)
        self.plugins = w3af_core_plugins(self)
        self.status = w3af_core_status()
        self.target = w3af_core_target()
        self.progress = progress()
        self.strategy = w3af_core_strategy(self)
        
        self._create_worker_pool()

        # FIXME: In the future, when the output_manager is not an awful singleton
        # anymore, this line should be removed and the output_manager object
        # should take a w3afCore object as a parameter in its __init__
        om.out.set_w3af_core(self)
        
        # Create the URI opener object
        self.uri_opener = ExtendedUrllib()
                
    def scan_start_hook(self):
        '''
        Create directories, threads and consumers required to perform a w3af
        scan. Used both when we init the core and when we want to clear all
        the previous results and state from an old scan and start again.
        
        @return: None
        '''
        # If this is not the first scan, I want to clear the old bug data that
        # might be stored in the exception_handler.
        self.exception_handler.clear()
        
        self.cleanup()
        
        # Create some directories, do this every time before starting a new
        # scan and before doing any other core init because these are widely
        # used
        self._home_directory()
        self._tmp_directory()
        
        enable_dns_cache()
        
        # Reset global sequence number generator
        consecutive_number_generator.reset()
               
        # Now that we know we're going to run a new scan, overwrite the old
        # strategy which might still have data stored in it and create a new
        # one  
        self.strategy = w3af_core_strategy(self)
        
        # And create these two again just to clear their internal states
        self.status = w3af_core_status()
        self.progress = progress()

        # Init the 404 detection for the whole framework
        fp_404_db = fingerprint_404_singleton(cleanup=True)
        fp_404_db.set_url_opener(self.uri_opener)
        fp_404_db.set_worker_pool(self.worker_pool)
    
    def start(self):
        '''
        The user interfaces call this method to start the whole scanning
        process.
        This method raises almost every possible exception, so please do your
        error handling!
        '''
        om.out.debug('Called w3afCore.start()')

        self.scan_start_hook()
        
        # This will help identify the total scan time
        self._start_time_epoch = time.time()

        try:
            # Just in case the GUI / Console forgot to do this...
            self.verify_environment()
        except Exception, e:
            error = ('verify_environment() raised an exception: "%s". This'
                     ' should never happen. Are you (UI developer) sure that'
                     ' you called verify_environment() *before* start() ?' % e)
            om.out.error(error)
            raise

        # Let the output plugins know what kind of plugins we're
        # using during the scan
        om.out.log_enabled_plugins(self.plugins.get_all_enabled_plugins(),
                                   self.plugins.get_all_plugin_options())

        self.status.start()

        try:
            self.strategy.start()
        except MemoryError:
            msg = 'Python threw a MemoryError, this means that your'\
                  ' OS is running very low in memory. w3af is going'\
                  ' to stop.'
            om.out.error(msg)
            raise
        except w3afMustStopByUserRequest, sbur:
            # I don't have to do anything here, since the user is the one that
            # requested the scanner to stop. From here the code continues at the
            # "finally" clause, which simply shows a message saying that the
            # scan finished.
            om.out.information('%s' % sbur)
        except w3afMustStopByUnknownReasonExc:
            #
            # TODO: Jan 31, 2011. Temporary workaround. Make w3af crash on
            # purpose so we can find out the *really* unknown error
            # conditions.
            #
            raise
        except w3afMustStopException, wmse:
            error = '\n**IMPORTANT** The following error was detected by'\
                    ' w3af and couldn\'t be resolved:\n%s\n' % wmse
            om.out.error(error)
        except Exception:
            om.out.error('\nUnhandled error, traceback: %s\n' %
                         traceback.format_exc())
            raise
        finally:

            self.status.scan_finished()

            time_spent = epoch_to_string(self._start_time_epoch)
            msg = 'Scan finished in %s' % time_spent
            
            try:
                om.out.information(msg)
            except:
                # In some cases we get here after a disk full exception
                # where the output manager can't even write a log message
                # to disk and/or the console. Seen this happen many times
                # in LiveCDs like Backtrack that don't have "real disk space"
                print msg

            self.strategy.stop()
            self.progress.stop()
        
            self.scan_end_hook()

    def _create_worker_pool(self):
        self.worker_pool = Pool(self.WORKER_THREADS,
                                worker_names='WorkerThread')
        
    def get_run_time(self):
        '''
        @return: The time (in minutes) between now and the call to start().
        '''
        now = time.time()
        diff = now - self._start_time_epoch
        run_time = diff / 60
        return run_time

    def cleanup(self):
        '''
        The GTK user interface calls this when a scan has been stopped
        (or ended successfully) and the user wants to start a new scan.
        All data from the kb is deleted.

        @return: None
        '''
        # Clean all data that is stored in the kb
        kb.cleanup()

        # Not cleaning the config is a FEATURE, because the user is most likely
        # going to start a new scan to the same target, and he wants the proxy,
        # timeout and other configs to remain configured as he did it the first
        # time.
        # reload(cf)

        # It is also a feature to keep the misc settings from the last run, this
        # means that we don't cleanup the misc settings.

        # Not calling:
        # self.plugins.zero_enabled_plugins()
        # because I wan't to keep the selected plugins and configurations

    def stop(self):
        '''
        This method is called by the user interface layer, when the user "clicks"
        on the stop button.

        @return: None. The stop method can take some seconds to return.
        '''
        om.out.debug('The user stopped the core, finishing threads...')
        
        if self.strategy is not None:
            self.strategy.stop()
        self.uri_opener.stop()
        
        stop_start_time = time.time()
        
        wait_max = 10 # seconds
        loop_delay = 0.5
        for _ in xrange(int(wait_max/loop_delay)):
            if not self.status.is_running():
                msg = '%s were needed to stop the core.' % epoch_to_string(stop_start_time)
                break
            
            try:
                time.sleep(loop_delay)
            except KeyboardInterrupt:
                msg = 'The user cancelled the cleanup process, forcing exit.'
                break
            
        else:
            msg = 'The core failed to stop in %s seconds, forcing exit.'
            msg = msg % wait_max
        
        om.out.debug(msg)
    
    def quit(self):
        '''
        The user wants to exit w3af ASAP, so we stop the scan and exit.
        '''
        self.stop()
        remove_temp_dir(ignore_errors=True)
        
    def pause(self, pause_yes_no):
        '''
        Pauses/Un-Pauses scan.
        @param trueFalse: True if the UI wants to pause the scan.
        '''
        self.status.pause(pause_yes_no)
        self.strategy.pause(pause_yes_no)
        self.uri_opener.pause(pause_yes_no)

    def verify_environment(self):
        '''
        Checks if all parameters where configured correctly by the user,
        which in this case is a mix of w3af_console, w3af_gui and the real
        (human) user.
        '''
        if not self.plugins.initialized:
            msg = 'You must call the plugins.init_plugins() method before'\
                  ' calling start().'
            raise w3afException(msg)

        if not cf.cf.get('targets'):
            raise w3afException('No target URI configured.')

        if not len(self.plugins.get_enabled_plugins('audit'))\
        and not len(self.plugins.get_enabled_plugins('crawl'))\
        and not len(self.plugins.get_enabled_plugins('infrastructure'))\
        and not len(self.plugins.get_enabled_plugins('grep')):
            raise w3afException(
                'No audit, grep or crawl plugins configured to run.')

    def scan_end_hook(self):
        '''
        This method is called when the process ends normally or by an error.
        '''
        try:
            # Close the output manager, this needs to be done BEFORE the end()
            # in uri_opener because some plugins (namely xml_output) use the data
            # from the history in their end() method. 
            om.out.end_output_plugins()
            
            # End the ExtendedUrllib (clear the cache and close connections)
            #
            # A new instance will be created at exploit_phase_prerequisites so that
            # we can perform some exploitation.
            self.uri_opener.end()
            
        except Exception:
            raise

        finally:
            # The scan has ended, terminate all workers
            #
            # The pool might be needed during the exploiting phase create a new
            # pool in exploit_phase_prerequisites()
            #self.worker_pool.terminate()
            #self.worker_pool.join()
            
            self.status.stop()
            self.progress.stop()

            # Remove all references to plugins from memory
            self.plugins.zero_enabled_plugins()
            
            self.exploit_phase_prerequisites()

            # No targets to be scanned.
            self.target.clear()

    def exploit_phase_prerequisites(self):
        '''
        This method is just a way to group all the things that we'll need 
        from the core during the exploitation phase. In other words, which
        internal objects do I need alive after a scan?
        '''
        self.uri_opener = ExtendedUrllib()
        self._create_worker_pool()

    def _home_directory(self):
        '''
        Handle all the work related to creating/managing the home directory.
        @return: None
        '''
        # Start by trying to create the home directory (linux: /home/user/.w3af/)
        create_home_dir()

        # If this fails, maybe it is because the home directory doesn't exist
        # or simply because it ain't writable|readable by this user
        if not verify_dir_has_perm(HOME_DIR, perm=os.W_OK | os.R_OK, levels=1):
            print('Either the w3af home directory "%s" or its contents are not'
                  ' writable or readable. Please set the correct permissions'
                  ' and ownership. This usually happens when running w3af as'
                  ' root using "sudo".' % HOME_DIR)
            sys.exit(-3)

    def _tmp_directory(self):
        '''
        Handle the creation of the tmp directory, where a lot of stuff is stored.
        Usually it's something like /tmp/w3af/<pid>/
        '''
        try:
            create_temp_dir()
        except Exception:
            msg = ('The w3af tmp directory "%s" is not writable. Please set '
                   'the correct permissions and ownership.' % TEMP_DIR)
            print msg
            sys.exit(-3)


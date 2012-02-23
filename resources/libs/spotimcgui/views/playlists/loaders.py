'''
Copyright 2011 Mikel Azkolain

This file is part of Spotimc.

Spotimc is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Spotimc is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Spotimc.  If not, see <http://www.gnu.org/licenses/>.
'''


import xbmc

from spotify import playlist, playlistcontainer, BulkConditionChecker, ErrorType

from spotify.utils.iterators import CallbackIterator

from spotify.utils.decorators import run_in_thread

import weakref

import threading



class PlaylistCallbacks(playlist.PlaylistCallbacks):
    __playlist_loader = None
    
    
    def __init__(self, playlist_loader):
        self.__playlist_loader = weakref.proxy(playlist_loader)
    
    
    def playlist_state_changed(self, playlist):
        self.__playlist_loader.check()
        self.__playlist_loader.start_loading()
    
    
    def playlist_metadata_updated(self, playlist):
        self.__playlist_loader.check()



class BasePlaylistLoader:
    __playlist = None
    __playlist_manager = None
    __checker = None
    
    #Playlist attributes
    __name = None
    __num_tracks = None
    __thumbnails = None
    __is_collaborative = None
    __is_loaded = None
    
    
    def __init__(self, session, playlist, playlist_manager):
        #Initialize all instance vars
        self.__playlist = playlist
        self.__playlist_manager = playlist_manager
        self.__checker = BulkConditionChecker()
        self.__is_loaded = False
        
        #Add the callbacks we are interested in
        playlist.add_callbacks(PlaylistCallbacks(self))
        
        #Fire playlist loading if neccesary
        if not playlist.is_in_ram(session):
            playlist.set_in_ram(session, True)
        
        #And finish the rest in the background
        self.start_loading()
    
    
    def get_playlist(self):
        return self.__playlist
    
    
    def _set_thumbnails(self, thumbnails):
        self.__thumbnails = thumbnails
    
    
    def get_thumbnails(self):
        return self.__thumbnails
    
    
    def _set_name(self, name):
        self.__name = name
    
    
    def get_name(self):
        return self.__name
    
    
    def get_num_tracks(self):
        return self.__num_tracks
    
    
    def get_tracks(self):
        return self.__playlist.tracks()
    
    
    def get_is_collaborative(self):
        return self.__is_collaborative
    
    
    def _track_is_ready(self, track, test_album=True, test_artists=True):
        def album_is_loaded():
            album = track.album()
            return album is not None and album.is_loaded()
        
        def artists_are_loaded():
            for item in track.artists():
                if item is None or not item.is_loaded():
                    return False
            return True
        
        #If track has an error stop further processing
        if track.error() not in [ErrorType.Ok, ErrorType.IsLoading]:
            return True
        
        #Always test for the track data
        if not track.is_loaded():
            return False
        
        #If album data was requested
        elif test_album and not album_is_loaded():
            return False
        
        #If artist data was requested
        elif test_artists and not artists_are_loaded():
            return False
        
        #Otherwise everything was ok
        else:
            return True
    
    
    def _wait_for_playlist(self):
        if not self.__playlist.is_loaded():
            self.__checker.add_condition(self.__playlist.is_loaded)
            self.__checker.complete_wait(10)
    
    
    def _wait_for_track_metadata(self, track):
        def test_is_loaded():
            return self._track_is_ready(
                track, test_album=True, test_artists=False
            )
        
        if not test_is_loaded():
            self.__checker.add_condition(test_is_loaded)
            self.__checker.complete_wait(10)
    
    
    def _load_thumbnails(self):
        pm = self.__playlist_manager
        
        #If playlist has an image
        playlist_image = self.__playlist.get_image()
        if playlist_image is not None:
            thumbnails = [pm.get_image_url(playlist_image)]
        
        #Otherwise get them from the album covers
        else:
            thumbnails = []
            for item in self.__playlist.tracks():
                #Wait until this track is fully loaded
                self._wait_for_track_metadata(item)
                
                #Check if item was loaded without errors
                if item.is_loaded() and item.error() == 0:
                    #Append the cover if it's new
                    image_id = item.album().cover()
                    image_url = pm.get_image_url(image_id)
                    if image_url not in thumbnails:
                        thumbnails.append(image_url)
                    
                    #If we reached to the desired thumbnail count...
                    if len(thumbnails) == 4:
                        break
        
        #If the stored thumbnail data changed...
        if self.__thumbnails != thumbnails:
            self.__thumbnails = thumbnails
            return True
    
    
    def _load_name(self):
        if self.__name != self.__playlist.name():
            self.__name = self.__playlist.name()
            return True
        else:
            return False
    
    
    def _load_num_tracks(self):
        if self.__num_tracks != self.__playlist.num_tracks():
            self.__num_tracks = self.__playlist.num_tracks()
            return True
        else:
            return False
    
    
    def _load_is_collaborative(self):
        if self.__is_collaborative != self.__playlist.is_collaborative():
            self.__is_collaborative = self.__playlist.is_collaborative()
            return True
        else:
            return False
    
    
    def _load_attributes(self):
        #Now check for changes
        has_changes = False
        
        if self._load_name():
            has_changes = True
        
        if self._load_num_tracks():
            has_changes = True
        
        if self._load_is_collaborative():
            has_changes = True
        
        #If we detected something different
        return has_changes
    
    
    def _add_condition(self, condition):
        self.__checker.add_condition(condition)
   
   
    def _wait_for_conditions(self, timeout):
        self.__checker.complete_wait(timeout)
    
    
    def check(self):
        self.__checker.check_conditions()
    
    
    def _set_loaded(self, status):
        self.__is_loaded = status 
    
    
    def is_loaded(self):
        return self.__is_loaded
    
    
    def start_loading(self):
        raise NotImplementedError()
    
    
    def __del__(self):
        print "PlaylistLoader __del__"



class ContainerPlaylistLoader(BasePlaylistLoader):
    __container_loader = None
    
    
    def __init__(self, session, playlist, playlist_manager, container_loader):
        self.__container_loader = weakref.proxy(container_loader)
        BasePlaylistLoader.__init__(self, session, playlist, playlist_manager)
    
    
    @run_in_thread(threads_per_class=10, single_instance=True)
    def start_loading(self):
        #Wait for the underlying playlist object
        self._wait_for_playlist()
        
        #And load the rest of the data
        has_changes = False
        
        if self._load_attributes():
            has_changes = True
        
        if self._load_thumbnails():
            has_changes = True
        
        #Mark the playlist as loaded
        self._set_loaded(True)
        
        if has_changes:
            self.__container_loader.update()



class FullPlaylistLoader(BasePlaylistLoader):
    def _check_track(self, track):
        def track_is_loaded():
            return self._track_is_ready(
                track, test_album=True, test_artists=True
            )
        
        #Add a check condition for this track if it needs one
        if not track_is_loaded():
            self._add_condition(track_is_loaded)
    
    
    def _load_all_tracks(self):
        #Iterate over the tracks to add conditions for them
        for item in self.get_tracks():
            self._check_track(item)
        
        #Wait until all tracks meet the conditions
        self._wait_for_conditions(20)
    
    
    @run_in_thread(threads_per_class=10, single_instance=True)
    def start_loading(self):
        #Wait for the underlying playlist object
        self._wait_for_playlist()
        
        #Load all the tracks
        self._load_all_tracks()
        
        #And load the rest of the data
        has_changes = False
        
        if self._load_attributes():
            has_changes = True
        
        if self._load_thumbnails():
            has_changes = True
        
        #Mark the playlist as loaded
        self._set_loaded(True)
        
        if has_changes:
            xbmc.executebuiltin("Action(Noop)")


class SpecialPlaylistLoader(BasePlaylistLoader):
    def __init__(self, session, playlist, playlist_manager, name, thumbnails):
        BasePlaylistLoader.__init__(self, session, playlist, playlist_manager)
        self._set_name(name)
        self._set_thumbnails(thumbnails)
    
    
    @run_in_thread(threads_per_class=10, single_instance=True)
    def start_loading(self):
        #Wait for the underlying playlist object
        self._wait_for_playlist()
        
        #And load the rest of the data
        has_changes = False
        
        if self._load_num_tracks():
            has_changes = True
        
        #Mark the playlist as loaded
        self._set_loaded(True)
        
        #Update ui
        if has_changes:
            xbmc.executebuiltin("Action(Noop)")


class ContainerCallbacks(playlistcontainer.PlaylistContainerCallbacks):
    __loader = None
    
    
    def __init__(self, loader):
        self.__loader = weakref.proxy(loader)
    
    
    def playlist_added(self, container, playlist, position):
        self.__loader.add_playlist(playlist, position)
        print "playlist added: #%d" % position
    
    
    def container_loaded(self, container):
        self.__loader.update()
    
    
    def playlist_removed(self, container, playlist, position):
        print "playlist removed #%d" % position
        self.__loader.remove_playlist(position)
        self.__loader.update()
    
    
    def playlist_moved(self, container, playlist, position, new_position):
        print "playlist moved %d -> %d" % (position, new_position)
        self.__loader.move_playlist(position, new_position)
        self.__loader.update()



class ContainerLoader:
    __session = None
    __container = None
    __playlist_manager = None
    __playlists = None
    __checker = None
    __loading_lock = None
    __list_lock = None
    __is_loaded = None
    
    
    def __init__(self, session, container, playlist_manager):
        self.__session = session
        self.__container = container
        self.__playlist_manager = playlist_manager
        self.__playlists = []
        self.__checker = BulkConditionChecker()
        self.__loading_lock = threading.RLock()
        self.__list_lock = threading.RLock()
        self.__is_loaded = False
        
        #Load the rest in the background
        self._start_load()
    
    
    def _fill_spaces(self, position):
        try:
            self.__list_lock.acquire()
            
            if position >= len(self.__playlists):
                for idx in range(len(self.__playlists), position + 1):
                    self.__playlists.append(None)
        
        finally:
            self.__list_lock.release()
    
    
    def is_playlist(self, position):
        playlist_type = self.__container.playlist_type(position)
        return playlist_type == playlist.PlaylistType.Playlist
    
    
    def add_playlist(self, playlist, position):
        try:
            self.__list_lock.acquire()
            
            #Ensure that it gets added in the correct position
            self._fill_spaces(position - 1)
            
            #Instantiate a loader if it's a real playlist
            if self.is_playlist(position):
                item = ContainerPlaylistLoader(
                    self.__session, playlist, self.__playlist_manager, self 
                )
            
            #Ignore if it's not a real playlist
            else:
                item = None
            
            #Insert the generated item
            self.__playlists.insert(position, item)
                
        
        finally:
            self.__list_lock.release()
    
    
    def remove_playlist(self, position):
        try:
            self.__list_lock.acquire()
            del self.__playlists[position]
        
        finally:
            self.__list_lock.release()
    
    
    def move_playlist(self, position, new_position):
        try:
            self.__list_lock.acquire()
            self.__playlists.insert(new_position, self.__playlists[position])
            
            #Calculate new position
            if position > new_position:
                position += 1
            
            del self.__playlists[position]
        
        finally:
            self.__list_lock.release()
    
    
    def _add_missing_playlists(self):
        #Ensure that the container and loader length is the same
        self._fill_spaces(self.__container.num_playlists() - 1)
        
        #Iterate over the container to add the missing ones
        for pos, item in enumerate(self.__container.playlists()):
            if self.is_playlist(pos) and self.__playlists[pos] is None:
                self.add_playlist(item, pos)
    
    
    def _load_container(self):
        #Wait for the container to be fully loaded
        self.__checker.add_condition(self.__container.is_loaded)
        self.__checker.complete_wait()
        
        #Fill the container with unseen playlists
        self._add_missing_playlists()
        
        #Add a load check for each playlist
        for item in self.__playlists:
            if item is not None and not item.is_loaded():
                self.__checker.add_condition(item.is_loaded)
        
        #Wait until all conditions became true
        self.__checker.complete_wait(self.__container.num_playlists() * 5)
        
        #Set the status of the loader
        self.__is_loaded = True
        
        #Finally tell the gui we are done
        xbmc.executebuiltin("Action(Noop)")
    
    
    @run_in_thread
    def _start_update(self):
        """
        Try gaining a lock.
        If we can't get one, another update is running, so do nothing.
        """
        if self.__loading_lock.acquire(False):
            try:
                self._load_container()
            
            finally:
                self.__loading_lock.release()
    
    
    @run_in_thread
    def _start_load(self):
        self.__loading_lock.acquire()
        
        try:
            """
            Register container callbacks so they start loading after
            this point. Too bad if they reach before.
            """
            self.__container.add_callbacks(ContainerCallbacks(self))
            
            #And take care of the rest
            self._load_container()
        
        finally:
            self.__loading_lock.release()
    
    
    def update(self):
        self.__checker.check_conditions()
        self._start_update()
    
    
    def is_loaded(self):
        return self.__is_loaded
    
    
    def playlist(self, index):
        return self.__playlists[index]
    
    
    def num_playlists(self):
        return len(self.__playlists)
    
    
    def playlists(self):
        return CallbackIterator(self.num_playlists, self.playlist)
    
    
    def get_container(self):
        return self.__container
    
    
    def __del__(self):
        print "ContainerLoader __del__"
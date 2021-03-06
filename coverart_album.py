# -*- Mode: python; coding: utf-8; tab-width: 4; indent-tabs-mode: nil; -*-
#
# Copyright (C) 2012 - fossfreedom
# Copyright (C) 2012 - Agustin Carrasco
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301  USA.

from gi.repository import RB
from gi.repository import GLib
from gi.repository import Gdk
from gi.repository import GdkPixbuf

import os
import cgi
import rb


class AlbumLoader(object):
    '''
    Utility class that manages the albums created for the coverart browser's
    source.
    '''
    # default chunk of albums to load at a time while filling the model
    DEFAULT_LOAD_CHUNK = 10

    def __init__(self, plugin, cover_model):
        '''
        Initialises the loader, getting the needed objects from the plugin and
        saving the model that will be used to assign the loaded albums.
        '''
        self.albums = {}
        self.db = plugin.shell.props.db
        self.cover_model = cover_model
        self.cover_db = RB.ExtDB(name='album-art')

        # connect the signal to update cover arts when added
        self.req_id = self.cover_db.connect('added',
            self._albumart_added_callback)

        # connect signals for updating the albums
        self.entry_changed_id = self.db.connect('entry-changed',
            self._entry_changed_callback)
        self.entry_added_id = self.db.connect('entry-added',
            self._entry_added_callback)
        self.entry_deleted_id = self.db.connect('entry-deleted',
            self._entry_deleted_callback)

        # initialise unkown cover for albums without cover
        Album.init_unknown_cover(plugin)

    def _albumart_added_callback(self, ext_db, key, path, pixbuf):
        '''
        Callback called when new album art added. It updates the pixbuf to the
        album defined by key.
        '''
        print "CoverArtBrowser DEBUG - albumart_added_callback"

        album_name = key.get_field("album")

        # use the name to get the album and update the cover
        if album_name in self.albums:
            self.albums[album_name].update_cover(pixbuf)

        print "CoverArtBrowser DEBUG - end albumart_added_callback"

    def _entry_changed_callback(self, db, entry, changes):
        '''
        Callback called when a RhythDB entry is modified. Updates the albums
        accordingly to the changes made on the db.

        :param changes: GValueArray with the RhythmDBEntryChange made on the
        entry.
        '''
        print "CoverArtBrowser DEBUG - entry_changed_callback"
        # look at all the changes and update the albums acordingly
        try:
            while True:
                change = changes.values

                if change.prop is RB.RhythmDBPropType.ALBUM:
                    # called when the album of a entry is modified
                    self._entry_album_modified(entry, change.old, change.new)

                elif change.prop is RB.RhythmDBPropType.HIDDEN:
                    # called when an entry gets hidden (e.g.:the sound file is
                    # removed.
                    self._entry_hidden(db, entry, change.new)

                # removes the last change from the GValueArray
                changes.remove(0)
        except:
            # we finished reading the GValueArray
            pass

        print "CoverArtBrowser DEBUG - end entry_changed_callback"

    def _entry_album_modified(self, entry, old_name, new_name):
        '''
        Called by entry_changed_callback when the modified prop is the album.
        Reallocates the entry into the album defined by new_name, removing
        it from the old_name album previously.
        '''
        print "CoverArtBrowser DEBUG - entry_album_modified"
        # find the old album and remove the entry
        self._remove_entry(entry, old_name)

        # add the entry to the album it belongs now
        self._allocate_entry(entry, new_name)

        print "CoverArtBrowser DEBUG - end entry_album_modified"

    def _entry_hidden(self, db, entry, hidden):
        '''
        Called by entry_changed_callback when the modified prop is the hidden
        prop.
        It removes/adds the entry to the albums acordingly.
        '''
        print "CoverArtBrowser DEBUG - entry_hidden"
        if hidden:
            self._entry_deleted_callback(db, entry)
        else:
            self._entry_added_callback(db, entry)

        print "CoverArtBrowser DEBUG - end entry_hidden"

    def _entry_added_callback(self, db, entry):
        '''
        Callback called when a new entry is added to the Rhythmbox's db.
        '''
        print "CoverArtBrowser DEBUG - entry_added_callback"
        self._allocate_entry(entry)

        print "CoverArtBrowser DEBUG - end entry_added_callback"

    def _entry_deleted_callback(self, db, entry):
        '''
        Callback called when a entry is deleted from the Rhythmbox's db.
        '''
        print "CoverArtBrowser DEBUG - entry_deleted_callback"
        self._remove_entry(entry)

        print "CoverArtBrowser DEBUG - end entry_deleted_callback"

    def _allocate_entry(self, entry, album_name=None):
        '''
        Allocates a given entry in to an album. If not album name is given,
        it's inferred from the entry metadata.
        '''
        if not album_name:
            album_name = entry.get_string(RB.RhythmDBPropType.ALBUM)

        if album_name in self.albums:
            album = self.albums[album_name]
            album.append_entry(entry)
        else:
            artist = entry.get_string(RB.RhythmDBPropType.ARTIST)
            album = Album(album_name, artist)
            self.albums[album_name] = album

            album.append_entry(entry)
            album.load_cover(self.cover_db)
            album.add_to_model(self.cover_model)

    def _remove_entry(self, entry, album_name=None):
        '''
        Removes an entry from the an album. If the album name is not provided,
        it's inferred from the entry metatada.
        '''
        if not album_name:
            album_name = entry.get_string(RB.RhythmDBPropType.ALBUM)

        if album_name in self.albums:
            album = self.albums[album_name]
            album.remove_entry(entry)

            # if the album is empty, remove it's reference
            if album.get_track_count() == 0:
                del self.albums[album_name]

    def load_albums(self):
        '''
        Initiates the process of recover, create and load all the albums from
        the Rhythmbox's db and their covers provided by artsearch plugin.
        Specifically, it throws the query against the RhythmDB.
        '''
        print "CoverArtBrowser DEBUG - load_albums"
        # build the query
        q = GLib.PtrArray()
        self.db.query_append_params(q,
            RB.RhythmDBQueryType.EQUALS,
            RB.RhythmDBPropType.TYPE,
            self.db.entry_type_get_by_name('song'))

        # create the model and connect to the completed signal
        qm = RB.RhythmDBQueryModel.new_empty(self.db)
        qm.connect('complete', self._query_complete_callback)

        # throw the query
        self.db.do_full_query_async_parsed(qm, q)

        print "CoverArtBrowser DEBUG - end load_albums"

    def _query_complete_callback(self, qm):
        '''
        Callback called when the asynchronous query made by load_albums
        finishes.
        Processes all the entries from the db and fills the model.
        '''
        qm.foreach(self._process_entry, None)

        self._fill_model()

    def _process_entry(self, model, tree_path, tree_iter, _):
        '''
        Process a single entry, allocating it to it's correspondent album or
        creating a new one if necesary.
        '''
        (entry,) = model.get(tree_iter, 0)

        album_name = entry.get_string(RB.RhythmDBPropType.ALBUM)
        artist = entry.get_string(RB.RhythmDBPropType.ARTIST)

        if album_name in self.albums.keys():
            album = self.albums[album_name]
        else:
            album = Album(album_name, artist)
            self.albums[album_name] = album

        album.append_entry(entry)

    def _fill_model(self):
        '''
        Fills the model defined for this loader with the info a covers from
        all the albums loaded.
        '''
        Gdk.threads_add_idle(GLib.PRIORITY_DEFAULT_IDLE,
            self._idle_load_callback,
            self.albums.values())

    def _idle_load_callback(self, albums):
        '''
        Idle callback that loads the albums by chunks, to avoid blocking the
        ui while doing it.
        '''
        for i in range(AlbumLoader.DEFAULT_LOAD_CHUNK):
            try:
                album = albums.pop()
                album.load_cover(self.cover_db)
                album.add_to_model(self.cover_model)
            except:
                # we finished loading
                return False

        # the list still got albums, keep going
        return True

    def search_cover_for_album(self, album, callback=lambda *_: None):
        '''
        Request to a given album to find it's cover. This call is generally
        made asynchronously, so a callback can be given to be called upon
        the finishing of the process.
        '''
        album.cover_search(self.cover_db, callback)


class Album(object):
    '''
    An specific album defined by it's name and with the ability to obtain it's
    cover and set itself in a treemodel.
    '''
    # cover used for those albums without one
    UNKNOWN_COVER = 'rhythmbox-missing-artwork.svg'

    def __init__(self, name, artist):
        '''
        Initialises the album with a name and it's artist's name.
        Initially, the album haves no cover, so the default Unknown cover is
        asigned.
        '''
        self.name = name
        self.artist = artist
        self.entries = []
        self.cover = Album.UNKNOWN_COVER

    def append_entry(self, entry):
        ''' Appends an entry to the album entries' list. '''
        self.entries.append(entry)

    def remove_entry(self, entry):
        '''
        Removes an entry from the album entrie's list. If the removed entry
        was the last one on the Album, it automatically removes itself from
        it's tree model.
        '''
        for e in self.entries:
            if rb.entry_equal(e, entry):
                self.entries.remove(e)
                break

        # if there aren't entries left, remove the album from the model
        if self.get_track_count() == 0:
            self.remove_from_model()

    def load_cover(self, cover_db):
        '''
        Tries to load the Album's cover from the provided cover_db. If no cover
        is found upon lookup, the Unknown cover is used.
        '''
        key = self.entries[0].create_ext_db_key(RB.RhythmDBPropType.ALBUM)
        art_location = cover_db.lookup(key)

        if art_location and os.path.exists(art_location):
            try:
                self.cover = Cover(art_location)
            except:
                self.cover = Album.UNKNOWN_COVER

    def cover_search(self, cover_db, callback):
        '''
        Activelly requests the Album's cover to the provided cover_db, calling
        the callback given once the process finishes (since it generally is
        asyncrhonous).
        '''
        key = self.entries[0].create_ext_db_key(RB.RhythmDBPropType.ALBUM)

        cover_db.request(key, callback, None)

    def add_to_model(self, model):
        '''
        Add this model to the tree model. For default, the info is assigned
        in the next order:
            column 0 -> string containing the album name and artist
            column 1 -> pixbuf of the album's cover.
            column 2 -> instance of this same album.
        '''
        self.model = model
        self.tree_iter = model.append(
            (cgi.escape('%s - %s' % (self.artist, self.name)),
            self.cover.pixbuf,
            self))

    def remove_from_model(self):
        ''' Removes this album from it's model. '''
        self.model.remove(self.tree_iter)

    def update_cover(self, pixbuf):
        ''' Updates this Album's cover using the given pixbuf. '''
        if pixbuf:
            self.cover = Cover(pixbuf=pixbuf)
            self.model.set_value(self.tree_iter, 1, self.cover.pixbuf)

    def get_track_count(self):
        ''' Returns the quantity of tracks stored on this Album. '''
        return len(self.entries)

    def calculate_duration_in_secs(self):
        '''
        Returns the duration of this album (given by it's tracks) in seconds.
        '''
        duration = 0

        for entry in self.entries:
            duration += entry.get_ulong(RB.RhythmDBPropType.DURATION)

        return duration

    def calculate_duration_in_mins(self):
        '''
        Returns the duration of this album in minutes. The duration is
        truncated.
        '''
        return self.calculate_duration_in_secs() / 60

    @classmethod
    def init_unknown_cover(cls, plugin):
        '''
        Classmethod that should be called to initialize the the global Unknown
        cover.
        '''
        if type(cls.UNKNOWN_COVER) is str:
            cls.UNKNOWN_COVER = Cover(
                rb.find_plugin_file(plugin, cls.UNKNOWN_COVER))

    def contains(self, searchtext):
        '''
        Indicates if the text provided is contained either in this album's name
        or artist's name.
        '''
        return searchtext == "" \
        or searchtext.lower() in self.artist.lower() \
        or searchtext.lower() in self.name.lower()


class Cover(object):
    ''' Cover of an Album. '''
    # default cover size
    COVER_SIZE = 92

    def __init__(self, file_path=None, pixbuf=None, width=COVER_SIZE,
        height=COVER_SIZE):
        '''
        Initialises a cover, creating it's pixbuf or adapting a given one.
        Either a file path or a pixbuf should be given to it's correct
        initialization.
        '''
        if pixbuf:
            self.pixbuf = pixbuf.scale_simple(width, height,
                 GdkPixbuf.InterpType.BILINEAR)
        else:
            self.pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(file_path,
                width, height)

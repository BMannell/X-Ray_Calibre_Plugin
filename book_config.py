#!/usr/bin/env python2
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2016, Samreen Zarroug & Alex Mayer'
__docformat__ = 'restructuredtext en'

import os
import re
import functools
from PyQt5.QtCore import *
from urllib import urlencode
from httplib import HTTPConnection
from calibre.ebooks.BeautifulSoup import BeautifulSoup

from PyQt5.Qt import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
from PyQt5.Qt import QLabel, QLineEdit, QPushButton, QScrollArea

from calibre import get_proxies
from calibre_plugins.xray_creator.lib.book import Book
from calibre_plugins.xray_creator.lib.shelfari_parser import ShelfariParser

from calibre.utils.config import JSONConfig
from calibre.library import current_library_path

class BookConfigWidget(QDialog):
    def __init__(self, db, ids, parent):
        QDialog.__init__(self, parent)
        self.resize(500,500)
        self._index = 0

        self._book_settings = []

        http_proxy = get_proxies(debug=False).get('http', None)
        if http_proxy:
            self._proxy = True
            self._http_address = ':'.join(http_proxy.split(':')[:-1])
            self._http_port = int(http_proxy.split(':')[-1])

            aConnection = HTTPConnection(self._http_address, self._http_port)
            aConnection.set_tunnel('www.amazon.com', 80)
            sConnection = HTTPConnection(self._http_address, self._http_port)
            sConnection.set_tunnel('www.shelfari.com', 80)
        else:
            aConnection = HTTPConnection('www.amazon.com')
            sConnection = HTTPConnection('www.shelfari.com')

        for book_id in ids:
            self._book_settings.append(BookSettings(db, book_id, aConnection, sConnection))

        self.v_layout = QVBoxLayout(self)

        self.setWindowTitle('title - author')

        # add asin and shelfari url text boxes
        self.asin_label = QLabel('ASIN:')
        self.asin_edit = QLineEdit('')
        self.asin_edit.textEdited.connect(self.edit_asin)
        self.v_layout.addWidget(self.asin_label)
        self.v_layout.addWidget(self.asin_edit)

        self.shelfari_url = QLabel('Shelfari URL:')
        self.shelfari_url_edit = QLineEdit('')
        self.shelfari_url_edit.textEdited.connect(self.edit_shelfari_url)
        self.v_layout.addWidget(self.shelfari_url)
        self.v_layout.addWidget(self.shelfari_url_edit)

        # add scrollable area for aliases
        self.scroll_area = QScrollArea()
        self.v_layout.addWidget(self.scroll_area)

        # add previous, ok, cancel, and next buttons
        self.buttons_layout = QHBoxLayout(None)
        self.buttons_layout.setAlignment(Qt.AlignRight)

        if len(ids) > 1:
            self.previous_button = QPushButton("Previous")
            self.previous_button.setEnabled(False)
            self.previous_button.setFixedWidth(100)
            self.previous_button.clicked.connect(self.previous)
            self.buttons_layout.addWidget(self.previous_button)

        self.OK_button = QPushButton("OK")
        self.OK_button.setFixedWidth(100)
        self.OK_button.clicked.connect(self.ok)
        self.buttons_layout.addWidget(self.OK_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedWidth(100)
        self.cancel_button.clicked.connect(self.cancel)
        self.buttons_layout.addWidget(self.cancel_button)

        if len(ids) > 1:
            self.next_button = QPushButton("Next")
            self.next_button.setFixedWidth(100)
            self.next_button.clicked.connect(self.next)
            self.buttons_layout.addWidget(self.next_button)

        self.v_layout.addLayout(self.buttons_layout)
        self.setLayout(self.v_layout)

        self.show_book_prefs(self._book_settings[self._index])
        self.show()

    def edit_asin(self, val):
        self._book_settings[self._index].asin = val

    def edit_shelfari_url(self, val):
        self._book_settings[self._index].shelfari_url = val

    def edit_aliases(self, term, val):
        self._book_settings[self._index].aliases = (term, val)

    def previous(self):
        self._index -= 1
        self.next_button.setEnabled(True)
        if self._index == 0:
            self.previous_button.setEnabled(False)
        self.show_book_prefs(self._book_settings[self._index])

    def ok(self):
        for book in self._book_settings:
            book.save()
        self.close()

    def cancel(self):
        self.close()

    def next(self):
        self._index += 1
        self.previous_button.setEnabled(True)
        if self._index == len(self._book_settings) - 1:
            self.next_button.setEnabled(False)
        self.show_book_prefs(self._book_settings[self._index])

    def show_book_prefs(self, book):
        self.setWindowTitle(book.title_and_author)
        self.asin_edit.setText(book.asin)
        self.shelfari_url_edit.setText(book.shelfari_url)

        self.aliases_widget = QWidget()
        self.aliases_layout = QGridLayout(self.aliases_widget)
        self.aliases_layout.setAlignment(Qt.AlignTop)

        # add aliases for current book
        for index, aliases in enumerate(sorted(book.aliases.items())):
            label = QLabel(aliases[0] + ':')
            label.setFixedWidth(125)
            self.aliases_layout.addWidget(label, index, 0)

            line_edit = QLineEdit(', '.join(aliases[1]))
            line_edit.setFixedWidth(300)
            line_edit.textEdited.connect(functools.partial(self.edit_aliases, aliases[0]))
            self.aliases_layout.addWidget(line_edit, index, 1)

        self.scroll_area.setWidget(self.aliases_widget)

class BookSettings(object):
    AMAZON_ASIN_PAT = re.compile(r'data\-asin=\"([a-zA-z0-9]+)\"')
    SHELFARI_URL_PAT = re.compile(r'href="(.+/books/.+?)"')
    HEADERS = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/html", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64; rv:46.0) Gecko/20100101 Firefox/46.0"}
    LIBRARY = current_library_path()

    def __init__(self, db, book_id, aConnection, sConnection):
        self._db = db
        self._book_id = book_id
        self._aConnection = aConnection
        self._sConnection = sConnection

        book_path = self._db.field_for('path', book_id).replace('/', os.sep)

        self._prefs = JSONConfig(os.path.join(book_path, 'book_settings'), base_path=self.LIBRARY)
        self._prefs.setdefault('asin', '')
        self._prefs.setdefault('shelfari_url', '')
        self._prefs.setdefault('aliases', {})
        self._prefs.commit()

        self._title = self._db.field_for('title', book_id)
        self._author = ' & '.join(self._db.field_for('authors', self._book_id))

        self.asin = self._prefs['asin']
        if self.asin == '':
            identifiers = self._db.field_for('identifiers', self._book_id)
            self.asin = self._db.field_for('identifiers', self._book_id)['mobi-asin'].decode('ascii') if 'mobi-asin' in identifiers.keys() else None
            if not self.asin:
                self.asin = self._get_asin()
            if self.asin:
                self._prefs['asin'] = self.asin

        self.shelfari_url = self._prefs['shelfari_url']
        if self.shelfari_url == '':
            if self._prefs['asin'] != '':
                url = self._search_shelfari(self._prefs['asin'])
            if not url and self.title != 'Unknown' and self.author != 'Unknown':
                url = self._search_shelfari(self.title_and_author)

            if url:
                self.shelfari_url = url
                self._prefs['shelfari_url'] = self.shelfari_url

        self._aliases = self._prefs['aliases']
        if len(self._aliases.keys()) == 0 and self.shelfari_url != '':
            shelfari_parser = ShelfariParser(self.shelfari_url)
            shelfari_parser.get_characters()
            shelfari_parser.get_terms()
            
            for char in shelfari_parser.characters.items():
                self.aliases = (char[1]['label'], '')
            
            for term in shelfari_parser.terms.items():
                self.aliases = (term[1]['label'], '')

            self._prefs['aliases'] = self.aliases

    @property
    def prefs(self):
        return self._prefs

    @property
    def title(self):
        return self._title
    
    @property
    def author(self):
        return self._author

    @property
    def title_and_author(self):
        return '%s - %s' % (self.title, self.author)

    @property
    def asin(self):
        return self._asin
    
    @asin.setter
    def asin(self, val):
        self._asin = val

    @property
    def shelfari_url(self):
        return self._shelfari_url
    
    @shelfari_url.setter
    def shelfari_url(self, val):
        self._shelfari_url = val

    @property
    def aliases(self):
        return self._aliases

    @aliases.setter
    def aliases(self, val):
        self._aliases[val[0]] =  val[1].replace(', ', ',').split(',')

    def save(self):
        self._prefs['asin'] = self.asin
        self._prefs['shelfari_url'] = self.shelfari_url
        self._prefs['aliases'] = self.aliases

    def _get_asin(self):
        query = urlencode({'keywords': '%s' % self.title_and_author})
        try:
            self._aConnection.request('GET', '/s/ref=sr_qz_back?sf=qz&rh=i%3Adigital-text%2Cn%3A154606011%2Ck%3A' + query[9:] + '&' + query, headers=self.HEADERS)
            response = self._aConnection.getresponse().read()
        except:
            try:
                self._aConnection.close()
                if self._proxy:
                    self._aConnection = HTTPConnection(self._http_address, self._http_port)
                    self._aConnection.set_tunnel('www.amazon.com', 80)
                else:
                    self._aConnection = HTTPConnection('www.amazon.com')

                self._aConnection.request('GET', '/s/ref=sr_qz_back?sf=qz&rh=i%3Adigital-text%2Cn%3A154606011%2Ck%3A' + query[9:] + '&' + query, headers=self.HEADERS)
                response = self._aConnection.getresponse().read()
            except:
                return None

        # check to make sure there are results
        if 'did not match any products' in response and not 'Did you mean:' in response and not 'so we searched in All Departments' in response:
            return None

        soup = BeautifulSoup(response)
        results = soup.findAll('div', {'id': 'resultsCol'})
       
        if not results or len(results) == 0:
            return None

        for r in results:
            if 'Buy now with 1-Click' in str(r):
                asinSearch = self.AMAZON_ASIN_PAT.search(str(r))
                if asinSearch:
                    asin = asinSearch.group(1)
                    mi = self._db.get_metadata(self._book_id)
                    identifiers = mi.get_identifiers()
                    identifiers['mobi-asin'] = asin
                    mi.set_identifiers(identifiers)
                    self._db.set_metadata(self._book_id, mi)
                    return asin

    def _search_shelfari(self, keywords):
        query = urlencode ({'Keywords': keywords})
        try:
            self._sConnection.request('GET', '/search/books?' + query)
            response = self._sConnection.getresponse().read()
        except:
            try:
                self._sConnection.close()
                if self._proxy:
                    self._sConnection = HTTPConnection(self._http_address, self._http_port)
                    self._sConnection.set_tunnel('www.shelfari.com', 80)
                else:
                    self._sConnection = HTTPConnection('www.shelfari.com')

                self._sConnection.request('GET', '/search/books?' + query)
                response = self._sConnection.getresponse().read()
            except:
                return None
        
        # check to make sure there are results
        if 'did not return any results' in response:
            return None

        urlsearch = self.SHELFARI_URL_PAT.search(response)
        if not urlsearch:
            return None

        return urlsearch.group(1)
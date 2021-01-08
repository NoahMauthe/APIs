from __future__ import annotations

import logging
import os

from google.protobuf.message import DecodeError

from API import GooglePlayAPI_pb2 as Proto
from API.Exceptions import ConfigurationError, Maximum

LOGGER = logging.getLogger('Crawler.GooglePlayAPI.Objects')
LOGGER.setLevel(logging.INFO)


class App(object):
    """
    A wrapper class for App objects saved as protocol buffers.
    The protobuf declaration is a modified version of the one used by Google Play
    """

    def __init__(self, data, base_dir=None, category=None):
        if base_dir:
            self.base_dir = base_dir
        else:
            self.base_dir = os.getenv('HOME')
        proto = Proto.App()
        proto.docid = data.docid
        proto.title = data.title
        proto.creator = data.creator
        if category:
            proto.category.CopyFrom(category)
        else:
            try:
                proto.category.id = data.outerCategoryIdContainer.categoryIdContainer.categoryId
            except AttributeError:
                try:
                    proto.category.CopyFrom(data.category)
                except AttributeError:
                    LOGGER.warning('Category for app was neither set by the store, nor by us')
                    proto.category.id = 'Unknown'
        proto.descriptionHtml = data.descriptionHtml
        proto.offer.extend(data.offer)
        proto.availability.CopyFrom(data.availability)
        proto.details.CopyFrom(data.details)
        proto.aggregateRating.CopyFrom(data.aggregateRating)
        proto.relatedLinks.CopyFrom(data.relatedLinks)
        proto.shareUrl = data.shareUrl
        proto.reviewsUrl = data.reviewsUrl
        proto.backendUrl = data.backendUrl
        proto.purchaseDetailsUrl = data.purchaseDetailsUrl
        proto.releaseInfo.CopyFrom(data.releaseInfo)
        proto.descriptionShort = data.descriptionShort
        self.proto = proto
        LOGGER.debug(f'Created App {self.package_name()}')

    def __str__(self):
        return str(self.proto)

    def __repr__(self):
        return self.package_name()

    def __hash__(self):
        return hash(self.package_name())

    def __eq__(self, other):
        return self.package_name() == other.package_name() if type(other) == App else False

    def offer_type(self):
        """Gives the offer type of the application.

        Returns
        -------
        int
            The offer type. Only applicable for Google Play.
        """
        return self.proto.offer[0].offerType

    def write_to_file(self):
        """Saves the app information to file in a protobuf representation.

        Returns
        -------
        str
            The path of the saved file.
        """
        """
        Saves this app to a file in it's protobuf notation
        This way, it can be parsed using the same constructor as aps received over the internet
        The file extension stands for Protocol buffer Apk INformation
        """
        file_name = f'{self.package_name()}({self.version_code()}).pain'
        dir_path = self.path()
        os.makedirs(dir_path, exist_ok=True)
        file_path = os.path.join(dir_path, file_name)
        with open(file_path, 'wb+') as file:
            file.write(self.proto.SerializeToString())
        LOGGER.debug(f'Wrote metadata for {self.package_name()} to {file_path}')
        return file_path

    def path(self):
        """Gives the path all files that belong to his app should be saved to.
            If it does not exist, it will be created.

        Returns
        -------
        str
            The path of the folder.
        """
        path = os.path.join(self.base_dir, self.store().replace(' ', '_'), self.package_name())
        return os.path.abspath(path)

    def apk_file(self):
        """Gives the path the apk file of this app should be saved to.
            If it does not exist, it will be created.

        Returns
        -------
        str
            The path of the folder.
        """
        return os.path.join(self.path(), f'{self.package_name()}({self.version_code()}).apk')

    def splits(self):
        """Gives the path apk splits of this app should be saved to.
            If it does not exist, it will be created.

        Returns
        -------
        str
            The path of the folder.
        """
        path = os.path.join(self.path(), 'splits')
        os.makedirs(path, exist_ok=True)
        return path

    def additional_files(self):
        """Gives the path additional files of this app should be saved to.
            If it does not exist, it will be created.

        Returns
        -------
        str
            The path to the folder.
        """
        path = os.path.join(self.path(), 'obb_files')
        os.makedirs(path, exist_ok=True)
        return path

    def store(self):
        """Gives the store this app was crawled from.

        Returns
        -------
        str
            The name of the store.
        """
        return self.proto.store

    def version(self):
        """The apps version string.

        Returns
        -------
        str
            The version string as specified by the app.
        """
        return self.proto.details.appDetails.versionString

    def upload_date(self):
        """Gives the date of the upload of the current version.

        Returns
        -------
        str
            The release date of the current version.
        """
        return self.proto.details.appDetails.uploadDate

    def release_date(self):
        """Gives the date of the initial release of the app.

        Returns
        -------
        str
            The initial release date.
        """
        for item in self.proto.releaseInfo.item:
            if item.label == 'Released on':
                return item.container.value

    def developer(self):
        """Gives the developer's name as specified in Google Play.

        Returns
        -------
        str
            The developers name.
        """
        return self.proto.creator

    @staticmethod
    def from_file(path):
        """Loads an app from the provided file.

        Parameters
        ----------
        path : str
            The path of the file to create the app from.

        Returns
        -------
        App
            The app that was loaded from disk.
        """
        with open(path, 'rb') as file:
            app = Proto.App.FromString(file.read())
            base_dir = os.path.abspath(os.path.dirname(path))
            if app.store == "Google Play":
                LOGGER.debug('Found Google Play app')
                return GooglePlayApp(app, base_dir)
            elif app.store == "F-Droid":
                LOGGER.debug('Found F-Droid app')
                return FDroidApp(app, base_dir)
            else:
                raise ConfigurationError(f'{app.store} is not a valid App Store!')

    def package_name(self) -> str:
        """The package name of the application.
            It has to be unique in that store.

        Returns
        -------
        str
            The unique package name.

        """
        return self.proto.docid

    def version_code(self):
        """Gives the version code as specified by the app.
            It is necessary to download the app.
            Note that this does not have any restrictions, an app can go e.g. from 1000 to 1 to 9000 if the author
             decides that is what he wants to do.

        Returns
        -------
        int
            The version code of the app.
        """
        return self.proto.details.appDetails.versionCode

    def average_rating(self):
        """
        Returns
        -------
        float
            The average rating the app received.
        """
        return self.proto.aggregateRating.starRating

    def all_ratings(self):
        """Gives an overview on the ratings the app received.

        Returns
        -------
        dict
            The rating, grouped by stars with the addition of total and average.
        """
        return {
            'average': self.average_rating(),
            'total': self.proto.aggregateRating.ratingsCount,
            'oneStar': self.proto.aggregateRating.oneStarRatings,
            'twoStar': self.proto.aggregateRating.twoStarRatings,
            'threeStar': self.proto.aggregateRating.threeStarRatings,
            'fourStar': self.proto.aggregateRating.fourStarRatings,
            'fiveStar': self.proto.aggregateRating.fiveStarRatings,
        }

    def category(self):
        """Returns the category id, necessary for further queries.

        Returns
        -------
        str
            The id of this category.
        """
        return self.proto.category.id

    def category_name(self):
        """The human readable name of the category this app belongs to.

        Returns
        -------
        str
            A human readable form of the category name.
        """
        try:
            category = self.proto.category.parent
            return f'{category.name} - {self.proto.category.name}'
        except AttributeError:
            return self.proto.category.name

    def permissions(self):
        """
        Returns
        -------
        list
            A list of permissions the app uses.
        """
        return self.proto.details.appDetails.permission

    def downloads(self):
        """Note that this method returns a string, not an integer.
            This is caused by the way Google represents these numbers to users.

        Returns
        -------
        str
            The download count for the app.
        """
        return self.proto.details.appDetails.numDownloads

    def contains_ads(self):
        """
        Returns
        -------
        bool
            True if the app contains ads
        """
        return self.proto.details.appDetails.containsAds


class Category(object):

    def __init__(self, data):
        self.proto = self._parse(data)

    def _parse(self, data):
        """
        Helper method to convert a protobuf object by Google into our custom format
        """
        proto = Proto.Category()
        proto.name = data.name
        proto.dataUrl = data.dataUrl
        try:
            proto.id = data.outerCategoryIdContainer.categoryIdContainer.categoryId
        except AttributeError:
            proto.id = data.id
        LOGGER.debug(f'Created Category {proto.name}')
        return proto

    def id(self):
        """Returns the category id, necessary for further queries.

        Returns
        -------
        str
            The id of this category.
        """
        return self.proto.id

    def name(self):
        """The human readable name of the category.

        Returns
        -------
        str
            A human readable form of the category name.
        """
        return self.proto.name

    def data(self):
        """Returns the data url associated with this object.
            This seems only useful for Subcategories as of now

        Returns
        -------
        str
            The data url as supplied by Google.
        """
        return self.proto.dataUrl

    def proto_obj(self) -> Proto.Category:
        """Returns the raw protobuf object this category is based on.

        Returns
        -------
        Message
            The protobuf message this category is based on.
        """
        return self.proto

    def __str__(self):
        return str(self.proto)


class SubCategory(Category):

    def __init__(self, data, parent):
        self.parent = parent
        super().__init__(data)
        self.proto.parent.CopyFrom(parent.proto_obj())

    def _parse(self, data) -> Proto.Category:
        """
        Convert a Google protobuf object into our own format
        """
        proto = Proto.Category()
        child = data.response.payload.listResponse.doc[0].child[0]
        proto.id = child.docid
        proto.name = child.title
        proto.dataUrl = data.url
        LOGGER.debug(f'Created Subcategory {proto.name} of {self.parent.name()}')
        return proto


class AppList(object):

    def __init__(self, data, subcategory, api):
        self.api = api
        self.store = api.store
        self.apps = []
        self.next_page_url = ''
        self.subcategory = subcategory
        self.base_dir = api.base_dir
        self._parse_response(data)

    def limit(self, limited):
        self.apps = limited
        return self

    def __getitem__(self, index):
        return self.apps[index]

    def __iter__(self):
        return iter(self.apps)

    def __len__(self):
        return len(self.apps)

    def more(self):
        """Get more Apps by using the nextPageUrl field and append them to this class.

        Returns
        -------
        AppList
            An extended version of the AppList, allows calls to be chained.
        """
        self.subcategory.proto.dataUrl = self.next_page_url
        # LOGGER.info(f'{"#"*80}\n{self.subcategory.proto.dataUrl}{"#"*80}\n')
        try:
            return self.api.discover_apps(self.subcategory, self)
        except DecodeError:
            raise Maximum

    def update(self, data):
        """Callback function working in conjunction with more.

        Parameters
        ----------
        data : Response
            An http response to the update query.

        Returns
        -------
        AppList
            self to allow chained calls.
        """
        before = len(self)
        try:
            self._parse_response(data)
        except (IndexError, AttributeError):
            pass
        after = len(self)
        if before == after:
            LOGGER.debug(f'Could not extend AppList for Category "{self.subcategory.parent.name()}'
                         f' - {self.subcategory.name()}"\n'
                         f'\tMaxed out at {len(self.apps)} apps')
            raise Maximum()
        LOGGER.debug(f'Updated AppList for Category "{self.subcategory.parent.name()} - {self.subcategory.name()}"\n'
                     f'\tNew number of apps is {len(self.apps)}')
        return self

    def _parse_response(self, data):
        try:
            list_info = data.payload.listResponse.doc[0].child[0]
        except IndexError as e:
            LOGGER.debug(f"Received erroneous data for {self.subcategory.parent.name()} - {self.subcategory.name()}\n"
                         f"\tProbably no more apps available")
            LOGGER.info(data)
            raise IndexError(e)
        if self.store == 'Google Play':
            self.apps.extend([GooglePlayApp(child, self.base_dir, self.subcategory.proto) for child in list_info.child])
        elif self.store == 'F-Droid':
            self.apps.extend([FDroidApp(child, self.base_dir, self.subcategory.proto) for child in list_info.child])
        else:
            raise ConfigurationError(f'There is no store called "{self.store}" currently implemented')
        next_url = list_info.containerMetadata.nextPageUrl
        self.next_page_url = next_url

    def __str__(self):
        return self.next_page_url

    def name(self):
        return f'{self.subcategory.parent.name()} - {self.subcategory.name()}'


class GooglePlayApp(App):

    def __init__(self, data, base_dir=None, category=None):
        super().__init__(data, base_dir, category)
        self.proto.store = 'Google Play'


class FDroidApp(App):

    def __init__(self, data, base_dir=None, category=None):
        super().__init__(data, base_dir, category)
        self.proto.store = 'F-Droid'


def init_logger(logger, level):
    global LOGGER
    LOGGER = logging.getLogger(logger.name + '.Objects')
    LOGGER.setLevel(level)

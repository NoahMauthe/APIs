import logging
import os

from bs4 import BeautifulSoup

from API import GooglePlayAPI_pb2 as Proto
from API.Exceptions import RequestError, Maximum
from API.Objects import AppList, SubCategory, Category, App, FDroidApp, init_logger
from API.Utils import get

LOGGER = logging.getLogger('Crawler.API.F-Droid')
LOGLEVEL = logging.INFO

SERVER = 'https://f-droid.org'


class CategoryError(Exception):
    pass


class API(object):

    def __init__(self, credentials=None, base_dir=None, logger=None):
        """ Creates a new API object to query the F-Droid store.
            As F-Droid is FOSS, there is no account required.

        Parameters
        ----------
        credentials : None
            Solely there to provide the same signature as the GooglePlayAPI.
        base_dir : str
            The path of the directory all apks and logs will be saved to.
        logger : logging.Logger
           A logger to attach the internal logging to.
        """
        global LOGGER
        if logger is None:
            LOGGER = logging.getLogger(__name__)
        else:
            LOGGER = logging.getLogger(logger.name + '.API.F-Droid')
        LOGGER.setLevel(LOGLEVEL)
        init_logger(LOGGER, LOGLEVEL)
        self.store = 'F-Droid'
        if base_dir:
            self.base_dir = base_dir
        else:
            self.base_dir = os.path.join(os.getenv('HOME'), 'apk_downloads')
            os.makedirs(self.base_dir, exist_ok=True)
        LOGGER.info('Initialized F-Droid API')

    def details(self, package):
        """Takes a package name and returns its details in protobuf format.
            Only use in case you want to query one specific package, not in an automated manner.

        Parameters
        ----------
        package : str
            The package name to query.
        Returns
        -------
        Proto.DocV2
            The protobuf representation of the package details.
        """
        """
        
        """
        return self._get_details(f'/en/packages/{package}')

    def _get_details(self, path):
        """Given a partial path on the F-Droid.org server, queries the server for the application details.

        Parameters
        ----------
        path : str
            A partial path on the F-Droid server. Can be automatically generated by discover_apps.

        Returns
        -------
        Proto.DocV2
            The protobuf representation of the package details.
        """
        if "/categories/" in path:
            raise CategoryError
        try:
            LOGGER.debug(f'{SERVER}{path}')
            response = get(f'{SERVER}{path}')
            LOGGER.debug(response.url)
        except ConnectionError:
            raise RequestError(f'\n\tUrl:\t{SERVER}{path}')
        if response.status_code != 200:
            raise RequestError(f'\n\tReason:\t{response.reason}\n\tCode:{response.status_code}'
                               f'\n\tUrl:\n{response.url}')
        package = BeautifulSoup(response.content.decode(), 'html.parser').find(class_='package')
        title = package.find(class_='package-name').text.strip()
        creator = 'F-Droid'
        description_short = package.find(class_='package-summary').text.strip()
        url = response.url[:-1] if response.url.endswith('/') else response.url
        docid = url.split('/')[-1]
        package_version = package.find(class_='package-version', id='latest')
        header = package_version.find(class_='package-version-header')
        links = header.find_all(name='a')
        version = links[0].attrs['name'].strip()
        version_code = int(links[1].attrs['name'].strip())
        html_description = package.find(class_='package-description').text.strip()
        proto = Proto.DocV2()
        proto.docid = docid
        proto.title = title
        proto.creator = creator
        proto.descriptionShort = description_short
        doc_details = Proto.DocumentDetails()
        details = Proto.AppDetails()
        details.versionCode = version_code
        details.versionString = version
        doc_details.appDetails.CopyFrom(details)
        proto.details.CopyFrom(doc_details)
        proto.descriptionHtml = html_description

        return proto

    def categories(self):
        """Retrieve all categories available in the F-Droid store at the moment.

        Returns
        -------
        list
            The categories as a list of Objects.Category class objects.
        """
        parent = Proto.Category()
        parent.id = parent.name = 'F-Droid'
        parent.dataUrl = ''
        LOGGER.info('Initialized Dummy Category "F-Droid"')
        return [Category(parent)]

    def subcategories(self, category, free=True):
        """Given a category, returns a list of its subcategories.
            Free is only there to ensure PlayStore compatibility.

        Parameters
        ----------
        category : Category
            The category to query for subcategories.
            In the case of F-Droid we only have one level of categories, so the sole parent "category" is F-Droid itself
        free : boolean
            Only exists to ensure PlayStore compatibility.

        Returns
        -------
        list
            A list of Objects.SubCategory.
        """
        response = get(SERVER + '/en/packages')
        if response.status_code != 200:
            raise RequestError(response.reason)
        return self._parse_categories(response, category)

    def discover_apps(self, subcategory, app_list=None):
        """Given a subcategory, discovers all apps contained therein.

        Parameters
        ----------
        subcategory : SubCategory
            The SubCategory to search.
        app_list : AppList
            Only there to ensure PlayStore compatibility.

        Returns
        -------
        AppList
            An AppList object containing the discovered apps.
        """
        LOGGER.info(f"Discovering apps for {subcategory.parent.name()} - {subcategory.name()}")
        wrapper = Proto.ResponseWrapper()
        if app_list is not None:
            raise Maximum
        payload = Proto.Payload()
        list_response = Proto.ListResponse()
        doc = list_response.doc.add()
        child = doc.child.add()
        response = get(f'{SERVER}{subcategory.data()}')
        if response.status_code != 200:
            raise RequestError(response.reason)
        soup = BeautifulSoup(response.content.decode(), 'html.parser')
        package_list = soup.find(id='package-list')
        packages = package_list.find_all(name='a')
        next_pages = package_list.find_all(class_='nav page')
        for next_page in next_pages:
            next_response = get(f'{SERVER}{next_page.find(name="a").attrs["href"]}')
            if next_response.status_code != 200:
                continue
            next_package_list = BeautifulSoup(next_response.content.decode(), 'html.parser').find(id='package-list')
            next_packages = next_package_list.find_all(name='a')
            packages += next_packages
        for package in packages:
            try:
                details = self._get_details(package.attrs['href'])
            except (RequestError, ConnectionError) as e:
                LOGGER.exception(e)
                continue
            except CategoryError:
                LOGGER.debug(f"{package.attrs['href']} is a category, not a package.")
                continue
            sub_child = child.child.add()
            sub_child.docid = details.docid
            sub_child.title = details.title
            sub_child.creator = details.creator
            sub_child.descriptionShort = details.descriptionShort
            sub_child.details.CopyFrom(details.details)
            sub_child.descriptionHtml = details.descriptionHtml
        payload.listResponse.CopyFrom(list_response)
        wrapper.payload.CopyFrom(payload)
        LOGGER.debug(wrapper)
        return AppList(wrapper, subcategory, self)

    def download(self, app):
        """Downloads an app as apk file and provides the path it can be found in.

        Parameters
        ----------
        app : App
            The app to download.

        Returns
        -------
        str
            The path the application was saved to.
        """
        LOGGER.debug(f'Downloading {app.package_name()}')
        app.write_to_file()
        response = get(f'{SERVER}/repo/{app.package_name()}_{app.version_code()}.apk')
        if response.status_code != 200:
            raise RequestError(f'\n\tReason:\t{response.reason}\n\tCode:{response.status_code}'
                               f'\n\tUrl:\n{response.url}')
        with open(app.apk_file(), 'wb+') as apk_file:
            apk_file.write(response.content)
        LOGGER.info(f'Successfully downloaded {app.package_name()} to {app.apk_file()}')
        return app.apk_file()

    def direct_download(self, package):
        """Directly download any app given by its package name.
            Intended for manual use.
        
        Parameters
        ----------
        package : str
            The package name the app is identified by.

        Returns
        -------
        str
            The path the application was saved to.
        """
        app = FDroidApp(self.details(package))
        return self.download(app)

    def _parse_categories(self, response, parent):
        """Given the response of a query for categories/subcategories, parses and converts them to protobuf format.

        Parameters
        ----------
        response : Response
            An html response create by the requests library
        parent : Category
            The parent category to group the subcategories under.

        Returns
        -------
        list
            The SubCategory elements parsed from the response organized in a list.
        """
        data = response.content.decode()
        soup = BeautifulSoup(data, 'html.parser')
        content = soup.find(class_='post-content')
        categories = list(map(lambda x: x.text, content.find_all(name='h3')))
        pages = list(map(lambda x: x.find(name='a').attrs['href'], content.find_all(name='p')))
        proto_categories = []
        LOGGER.debug(f'Converting {len(categories)} categories to protobuf format')
        for i in range(len(categories)):
            prefetch = Proto.PreFetch()
            wrapper = Proto.ResponseWrapper()
            prefetch.url = pages[i]
            payload = Proto.Payload()
            list_response = Proto.ListResponse()
            doc = list_response.doc.add()
            child = doc.child.add()
            child.title = child.docid = categories[i]
            payload.listResponse.CopyFrom(list_response)
            wrapper.payload.CopyFrom(payload)
            prefetch.response.CopyFrom(wrapper)
            proto_categories.append(SubCategory(prefetch, parent))
            LOGGER.debug(f'Progress: {len(proto_categories):>3} / {len(categories)}')
        return proto_categories
import logging
import os
from typing import AnyStr

import toml
from google.protobuf.message import DecodeError

from API.DeviceConfig import DeviceConfig
from API.Exceptions import ConfigurationError, LoginException, AuthenticationError, RequestError, Retry, Wait
from API.GooglePlayAPI_pb2 import AndroidCheckinRequest, UploadDeviceConfigRequest, \
    AndroidCheckinResponse, ResponseWrapper
from API.Objects import AppList, GooglePlayApp, SubCategory, Category, App, init_logger
from API.Utils import verbose_post, get_token, subcategory_list, category_list, encrypt_password, get

LOGGER = logging
LOGLEVEL = logging.INFO

SERVER = 'https://android.clients.google.com/'
LOCALE = 'en_US'


class API(object):

    def __init__(self, credential_file, device='bacon', base_dir=None, logger=None):
        """ Creates a new API object to query the Google Play Store.
            You need to supply credentials for a Google Account in order to use it.

        Parameters
        ----------
        credential_file : str
            The path of the credential file.
        base_dir : str
            The path of the directory all apks and logs will be saved to.
        logger : logging.Logger
           A logger to attach the internal logging to.
        """
        global LOGGER
        if logger is None:
            LOGGER = logging.getLogger(__name__)
        else:
            LOGGER = logging.getLogger(logger.name + '.API.PlayStore')
        LOGGER.setLevel(LOGLEVEL)
        init_logger(LOGGER, LOGLEVEL)
        self.store = 'Google Play'
        self._use_device(device)
        self.dfe_cookie = None
        self.device_config_token = None
        self.device_checkin_consistency_token = None
        self.logged_in = False
        self.credential_file = credential_file
        if base_dir:
            self.base_dir = base_dir
        else:
            self.base_dir = os.getenv('HOME')
        try:
            credentials = toml.load(self.credential_file)['account']
            self.auth_token = credentials.get('auth_token', None)
            self.android_id = credentials.get('androidID', None)
            self.mail = credentials['mail']
            self.password = credentials['password']
        except (KeyError, FileNotFoundError) as e:
            LOGGER.error('Invalid configuration file!')
            raise ConfigurationError('Invalid configuration file!', e)
        LOGGER.info('Got a valid configuration file')
        self._login()

    def _login(self):
        """Performs a login to Google Play if necessary.
            Returns itself, so chained calls are possible.

        Returns
        -------
        API
            The API a login was requested on.
        """
        if self.device is None:
            raise ConfigurationError("No device configured!")
        if self.logged_in:
            return self
        if self.android_id and self.auth_token:
            try:
                return self._login_via_token()
            except LoginException:
                LOGGER.exception('Trying login via password now')
        return self._login_via_password()

    def _use_device(self, device):
        """Tells the API to use a specific device.
            May influence the available apps.

        Parameters
        ----------
        device : str
            The codename of the device to use.
            Take a look at resources/devices.toml for an overview

        Returns
        -------
        API
            The API a login was requested on.
        """
        dir_path = os.path.dirname(os.path.realpath(__file__))
        devices = toml.load(os.path.join(dir_path, 'resources', 'devices.toml'))
        if device not in devices.keys():
            raise ConfigurationError('Please provide one of the preconfigured devices!\n'
                                     '\tUse "get_devices()" to list them all')
        self.device = DeviceConfig(devices[device])
        return self

    def _login_via_token(self):
        """Tries to perform a login via token, as there is a limit on the number of logins via password.
            The token is intended to be reused and will be checked for validity.

        Returns
        -------
        API
            The API a login was requested on.
        """
        try:
            self._home()
            self.logged_in = True
            LOGGER.info("Successfully logged in via token")
            return self
        except AuthenticationError:
            LOGGER.exception("Logging in via token failed, removing invalid tokens")
            out = {'account': {
                'user': self.mail,
                'password': self.password
            }}
            with open(self.credential_file, 'w+') as file:
                toml.dump(out, file)
            raise LoginException

    def _login_via_password(self):
        """Tries to perform a login with the provided credentials.

        Returns
        -------
        API
            The API a login was requested on.
        """
        auth_string = encrypt_password(self.mail, self.password)
        ac2dm_token = self._retrieve_ac2dm_token(auth_string)
        self.android_id = self._issue_checkin(ac2dm_token)
        self._authorize(auth_string)
        self._upload_device_configuration()
        self._update_credentials()
        self.logged_in = True
        LOGGER.info("Successfully logged in via password")
        return self

    def _retrieve_ac2dm_token(self, auth_string):
        """Retrieves an ac2dm token, part of the login procedure.
            Should never be called on its own.

        Parameters
        ----------
        auth_string : str
            An authentication string derived from Google Play credentials.

        Returns
        -------
        str
            The retrieved token.
        """
        LOGGER.info(f'Retrieving ac2dm-Token with authentication string {auth_string}')
        login_parameters, login_headers = self._login_parameters(auth_string)
        login_headers['app'] = 'com.google.android.gms'
        response = verbose_post('https://android.clients.google.com/auth',
                                data=login_parameters, headers=login_headers)
        ac2dm_token = get_token(response, 'auth')
        return ac2dm_token

    def _login_parameters(self, auth_string):
        """Builds the required login parameters from the current configuration.

        Parameters
        ----------
        auth_string : str
            An authentication string derived from Google Play credentials.

        Returns
        -------
        dict
            The login parameters as a dict to be used in a query.
        dict
            The login headers as a dict to be used in a query.
        """
        sig = '38918a453d07199354f8b19af05ec6562ced5788'
        login_parameters = {
            'Email': self.mail,
            'EncryptedPasswd': auth_string,
            'add_account': '1',
            'accountType': 'HOSTED_OR_GOOGLE',
            'google_play_services_version': self.device.gsf.version,
            'has_permission': '1',
            'source': 'android',
            'device_county': 'en',
            'lang': 'en_US',
            'client_sig': sig,
            'callerSig': sig,
            'service': 'ac2dm',
            'callerPkg': 'com.android.google.gms'
        }
        login_headers = {
            'User-Agent': f'GoogleAuth/1.4 ({self.device.build.device} {self.device.build.id}); gzip'.replace('"', ''),
        }
        if self.android_id:
            login_headers['device'] = f'{self.android_id:x}'
        return login_parameters, login_headers

    def _home(self):
        """Queries the Google Play Store for its landing page.
            Only used to determine the validity of a previously issued token.
        """
        headers = self._base_headers()
        parameters = {
            'c': 3,
            'nocache_isui': True
        }

        response = get('https://android.clients.google.com/fdfe/homeV2',
                       headers=headers,
                       params=parameters,
                       verify=True)
        message = ResponseWrapper.FromString(response.content)
        if message.commands.displayErrorMessage != "":
            raise AuthenticationError(message.commands.displayErrorMessage)

    def _issue_checkin(self, ac2dm_token):
        """Perform a checkin (two actually), which is necessary to complete a login to Google Play.

        Parameters
        ----------
        ac2dm_token : str
            An ac2dm token issued by Google Play.
        Returns
        -------
        str
            An Android ID.
        """
        headers = self._base_headers()
        headers['Content-Type'] = 'application/x-protobuf'
        request = AndroidCheckinRequest()
        request.id = 0
        request.checkin.CopyFrom(self.device.get_checkin())
        request.locale = 'em_US'
        request.timeZone = 'UTC'
        request.version = 3
        request.deviceConfiguration.CopyFrom(self.device.get_device_config())
        request.fragment = 0
        data = request.SerializeToString()
        response = verbose_post('https://android.clients.google.com/checkin',
                                data=data, headers=headers)
        proto_response = AndroidCheckinResponse()
        proto_response.ParseFromString(response.content)
        self.device_checkin_consistency_token = proto_response.deviceCheckinConsistencyToken
        android_id = proto_response.androidId
        security_token = proto_response.securityToken
        # TODO We may not need the second checkin
        second_request = request
        second_request.id = android_id
        second_request.securityToken = security_token
        second_request.accountCookie.append(f'[{self.mail}]')
        second_request.accountCookie.append(ac2dm_token)
        second_data = second_request.SerializeToString()
        verbose_post('https://android.clients.google.com/checkin',
                     data=second_data, headers=headers)
        LOGGER.info(f'Successfully checked in, got Android id {android_id}')
        return android_id

    def _base_headers(self):
        """Builds the base headers for the given device.

        Returns
        -------
        dict
            The base headers as a dict to be used in a query.
        """
        headers = {
            'Accept-Language': LOCALE.replace('_', '-'),
            'User-Agent': self._user_agent(),
            'X-DFE-Client-Id': 'am-android-google',
            'X-DFE-MCCMNC': str(self.device.celloperator),
            'X-DFE-Network-Type': '4',
        }
        if self.android_id is not None:
            headers["X-DFE-Device-Id"] = f'{self.android_id:x}'
        if self.auth_token is not None:
            headers['Authorization'] = f'GoogleLogin auth={self.auth_token}'
        if self.device_config_token is not None:
            headers["X-DFE-Device-Config-Token"] = self.device_config_token
        if self.device_checkin_consistency_token is not None:
            headers["X-DFE-Device-Checkin-Consistency-Token"] = self.device_checkin_consistency_token
        return headers

    def _user_agent(self):
        """Builds the user agent for the device at hand.

        Returns
        -------
        str
            The user agent as one string.
        """
        try:
            version_string = self.device.vending.versionstring
        except AttributeError:
            version_string = '8.4.19.V-all [0] [FP] 175058788'
        user_agent = f'Android-Finsky/{version_string} (api=3,' \
                     f'versionCode={self.device.vending.version},' \
                     f'sdk={self.device.build.version.sdk_int},' \
                     f'device={self.device.build.device},' \
                     f'hardware={self.device.build.hardware},' \
                     f'product={self.device.build.product},' \
                     f'platformVersionRelease={self.device.build.version.release},' \
                     f'model={self.device.build.model},' \
                     f'buildId={self.device.build.id},' \
                     f'supportedAbis={";".join(self.device.platforms)}'.replace('"', '')
        return user_agent

    def _upload_device_configuration(self):
        """Uploads the device configuration to Google Play.
            Necessary for any login as we simulate an Android device.
        """
        LOGGER.info(f'Uploading Device Configuration for {self.device.userreadablename}')
        upload = UploadDeviceConfigRequest()
        upload.deviceConfiguration.CopyFrom(self.device.get_device_config())
        headers = self._base_headers()
        headers['X-DFE-Enabled-Experiments'] = "cl:billing.select_add_instrument_by_default"
        headers['X-DFE-Unsupported-Experiments'] = ('nocache:billing.use_charging_poller,'
                                                    'market_emails,buyer_currency,prod_baseline,'
                                                    'checkin.set_asset_paid_app_field, '
                                                    'shekel_test,content_ratings,buyer_currency_in_app,'
                                                    'nocache:encrypted_apk,recent_changes')
        headers['X-DFE-SmallestScreenWidthDp'] = "320"
        headers['X-DFE-Filter-Level'] = "3"
        data = upload.SerializeToString()
        response = verbose_post('https://android.clients.google.com/fdfe/uploadDeviceConfig',
                                data=data, headers=headers)
        proto_response = ResponseWrapper.FromString(response.content)
        try:
            if proto_response.payload.HasField('uploadDeviceConfigResponse'):
                self.device_config_token = proto_response.payload.uploadDeviceConfigResponse.uploadDeviceConfigToken
        except ValueError:
            pass

    def _authorize(self, auth_string):
        """Authorizes a login to Google Play.

        Parameters
        ----------
        auth_string : str
            The authorization string as issued by Google Play.
        """
        params, headers = self._login_parameters(auth_string)
        params['app'] = headers['app'] = 'com.android.vending'
        params['service'] = 'androidmarket'
        response = verbose_post('https://android.clients.google.com/auth', data=params, headers=headers)
        master_token = get_token(response, 'token')
        params['Token'] = master_token
        params['check_email'] = '1'
        params['token_request_options'] = 'CAA4AQ=='
        params['system_partition'] = '1'
        params['_opt_is_called_from_account_manager'] = '1'
        params.pop('Email')
        params.pop('EncryptedPasswd')
        response = verbose_post('https://android.clients.google.com/auth', data=params, headers=headers)
        second_token = get_token(response, 'auth')
        self.auth_token = second_token
        LOGGER.info('Successfully authorized the device with Google Play')

    def _update_credentials(self):
        """Updates the credentials with the Android Id and the authorization token for further communication.
            Saves them back to the specified credential file.
        """
        LOGGER.info(f'Writing token to credential file "{self.credential_file}" for subsequent logins')
        with open(self.credential_file, 'w+') as file:
            toml.dump({'account': {
                'mail': self.mail,
                'password': self.password,
                'androidID': self.android_id,
                'auth_token': self.auth_token
            }}, file)

    def details(self, package):
        """Retrieves the details for an app given its package name.
            Intended for manual use only.

        Parameters
        ----------
        package : str
            A package name.

        Returns
        -------
        DocV2
            The details of the application in protobuf format.
        """
        self._login()
        response = get(SERVER + 'fdfe/details',
                       params={'doc': package},
                       headers=self._base_headers())
        proto_response = ResponseWrapper.FromString(response.content)
        if proto_response.commands.displayErrorMessage:
            raise RequestError(proto_response.commands.displayErrorMessage)
        return proto_response.payload.detailsResponse.docV2

    def categories(self):
        """Retrieves all categories available in the PlayStore at the moment.

        Returns
        -------
        list
            A list of categories in protobuf format.
        """
        self._login()
        response = get(SERVER + 'fdfe/browse',
                       params={'c': 3},
                       headers=self._base_headers())
        try:
            proto_response = ResponseWrapper.FromString(response.content)
        except DecodeError:
            LOGGER.error(f'Categories query provided invalid data\n'
                         f'Without categories, we cannot proceed. Exiting now.')
            LOGGER.error(response.content)
            exit(1)
        if proto_response.commands.displayErrorMessage:
            raise RequestError(proto_response.commands.displayErrorMessage)
        return category_list(proto_response)

    def subcategories(self, category, free=True):
        """Given a category, retrieves its subcategories.
            In Google Play, theses are grouped by Top Selling, Top Grossing, etc.
            If free is set, only categories that may contain free Applications are returned.
            Note that these may include e.g. Top Grossing due to In App purchases.

        Parameters
        ----------
        category : Category
            The category to query for subcategories.
        free : bool
            Specifies whether or not only free applications should be returned.
            Normally, this should be true, otherwise, the applications need to be purchased on the Google Play Account.
            This functionality is not supported by this API.

        Returns
        -------
        list
            A list of subcategories.
        """
        self._login()
        response = get(SERVER + 'fdfe/browse',
                       params={'c': 3,
                               'cat': category.id()},
                       headers=self._base_headers())
        try:
            proto_response = ResponseWrapper.FromString(response.content)
        except DecodeError:
            LOGGER.error(f'Category{category.name()} provided invalid data\n'
                         f'\tCould not retrieve subcategories')
            LOGGER.error(response.content)
            return []
        if proto_response.commands.displayErrorMessage:
            raise RequestError(proto_response.commands.displayErrorMessage)
        return list(filter(lambda x: 'paid' not in x.id() if free else lambda x2: True,
                           subcategory_list(proto_response, category)))

    def discover_apps(self, subcategory, app_list=None):
        """Given a subcategory, discovers all apps contained therein.

        Parameters
        ----------
        subcategory : SubCategory
            The SubCategory to search.
        app_list : AppList
            If an AppList is provided, it will be extended instead of creating a new one.

        Returns
        -------
        AppList
            An AppList object containing the discovered apps.
        """
        # LOGGER.info(f"Discovering apps for {subcategory.parent.name()} - {subcategory.name()}")
        self._login()
        # LOGGER.info(f'at {SERVER}fdfe/{subcategory.data()}')
        response = get(SERVER + f'fdfe/{subcategory.data()}',
                       headers=self._base_headers())
        proto_response = ResponseWrapper.FromString(response.content)
        # except DecodeError:
        #     LOGGER.error(f'Subcategory {subcategory.name()} of {subcategory.parent.name()} provided invalid data\n'
        #                  f'\tCould not initialize AppList')
        #     return app_list if app_list else []
        if proto_response.commands.displayErrorMessage:
            raise RequestError(proto_response.commands.displayErrorMessage)
        if app_list:
            return app_list.update(proto_response)
        else:
            try:
                return AppList(proto_response, subcategory, self)
            except IndexError:
                LOGGER.error(f'Subcategory {subcategory.name()} of {subcategory.parent.name()} provided invalid data\n'
                             f'\tCould not initialize AppList')
                return []

    def _purchase_free(self, app, data):
        """"Purchases" an application. Google Play requires this even for free applications.
            Basically, it is used to associate the application with the provided account.
            Additionally, this returns a download token required to get the app from the server.
        
        Parameters
        ----------
        app : App
            The app to purchase.
        data : dict
            Parameters required for a successful query.

        Returns
        -------
        str
            A download token required to access the app on the server.
        """
        response = verbose_post(SERVER + 'fdfe/purchase',
                                data=data,
                                headers=self._base_headers())
        proto_response = ResponseWrapper.FromString(response.content)
        error = proto_response.commands.displayErrorMessage
        if error == "":
            return proto_response.payload.buyResponse.downloadToken
        elif error == 'Can\'t install. Please try again later.':
            raise Retry(app.package_name())
        elif 'busy' in error:
            raise Wait(app.package_name())
        else:
            raise RequestError(error)

    def download(self, app):
        """Downloads an application given by an object.
            Note that the purchase is handled automatically, just like the download of additional files and split apks.
            This method is intended for automatic access by a crawler that received the App object from this API.
        
        Parameters
        ----------
        app : App
            The app to download.

        Returns
        -------
        str
            The path the app's apk file was downloaded to.
        """
        """
        Given an app, purchases it and downloads all the corresponding files.
        Purchasing is necessary for free apps to receive a download token
        :returns: The file path to the .apk
        """
        LOGGER.info(f'Downloading {app.package_name()}')
        self._login()
        app.write_to_file()
        params = {
            'ot': app.offer_type(),
            'doc': app.package_name(),
            'vc': str(app.version_code())
        }
        download_token = self._purchase_free(app, params)
        params['dtok'] = download_token
        response = get(SERVER + 'fdfe/delivery',
                       params=params,
                       headers=self._base_headers())
        proto_response = ResponseWrapper.FromString(response.content)
        error = proto_response.commands.displayErrorMessage
        if error != '':
            if 'busy' in error:
                raise Wait('Server was busy')
            else:
                raise RequestError(error)
        elif proto_response.payload.deliveryResponse.appDeliveryData.downloadUrl == '':
            LOGGER.error(f'App {app.package_name()} was not purchased!')
            return ''
        cookie = proto_response.payload.deliveryResponse.appDeliveryData.downloadAuthCookie[0]
        download_response = get(url=proto_response.payload.deliveryResponse.appDeliveryData.downloadUrl,
                                cookies={str(cookie.name): str(cookie.value)},
                                headers=self._base_headers())
        with open(app.apk_file(), 'wb+') as apk_file:
            apk_file.write(download_response.content)
        LOGGER.debug(f'Successfully downloaded apk to {app.apk_file()}')
        for apk_split in proto_response.payload.deliveryResponse.appDeliveryData.split:
            split_response = get(url=apk_split.downloadUrl,
                                 headers=self._base_headers())
            with open(app.splits() + apk_split.name, 'wb+') as split_file:
                split_file.write(split_response.content)
        obb_type = {
            0: 'main',
            1: 'patch'
        }
        for obb in proto_response.payload.deliveryResponse.appDeliveryData.additionalFile:
            obb_response = get(url=obb.downloadUrl,
                               headers=self._base_headers())
            obb_file_name = f'{obb_type[obb.fileType]}.{obb.versionCode}.{app.package_name()}.obb'
            with open(app.additional_files() + obb_file_name, 'wb+') as obb_file:
                obb_file.write(obb_response.content)
        return app.apk_file()

    def direct_download(self, package: str) -> AnyStr:
        """Directly downloads an application identified by its package name.
            This methods is intended for manual use only.

        Parameters
        ----------
        package : str
            The package name identifying the application.

        Returns
        -------
        str
            The path the app's apk file was downloaded to.
        """
        self._login()
        app = GooglePlayApp(self.details(package))
        return self.download(app)

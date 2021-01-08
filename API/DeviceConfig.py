from time import time

from API import GooglePlayAPI_pb2


class DeviceConfig(object):

    def __init__(self, config):
        self.config = config
        for k in config.keys():
            setattr(self, k.lower(), parse_dict(config[k]))

    def __str__(self):
        return str(self.config)

    def get_build(self):
        android_build = GooglePlayAPI_pb2.AndroidBuildProto()
        android_build.id = self.build.fingerprint
        android_build.product = self.build.hardware
        android_build.carrier = self.build.brand
        android_build.radio = self.build.radio
        android_build.bootloader = self.build.bootloader
        android_build.device = self.build.device
        android_build.sdkVersion = int(self.build.version.sdk_int)
        android_build.model = self.build.model
        android_build.manufacturer = self.build.manufacturer
        android_build.buildProduct = self.build.product
        android_build.client = self.client
        android_build.otaInstalled = False
        android_build.timestamp = int(time() / 1000)
        android_build.googleServices = self.gsf.version
        return android_build

    def get_checkin(self):
        android_checkin = GooglePlayAPI_pb2.AndroidCheckinProto()
        android_checkin.build.CopyFrom(self.get_build())
        android_checkin.lastCheckinMsec = 0
        android_checkin.cellOperator = str(self.celloperator)
        android_checkin.simOperator = str(self.simoperator)
        android_checkin.roaming = self.roaming
        android_checkin.userNumber = 0
        return android_checkin

    def get_device_config(self):
        device_config = GooglePlayAPI_pb2.DeviceConfigurationProto()
        device_config.touchScreen = self.touchscreen
        device_config.keyboard = self.keyboard
        device_config.navigation = self.navigation
        device_config.screenLayout = self.screenlayout
        device_config.hasHardKeyboard = self.hashardkeyboard
        device_config.hasFiveWayNavigation = self.hasfivewaynavigation
        device_config.screenDensity = self.screen.density
        device_config.screenWidth = self.screen.width
        device_config.screenHeight = self.screen.height
        device_config.glEsVersion = self.gl.version
        for lib in self.sharedlibraries:
            device_config.systemSharedLibrary.append(lib)
        for lib in self.platforms:
            device_config.nativePlatform.append(lib)
        for lib in self.locales:
            device_config.systemSupportedLocale.append(lib)
        for lib in self.features:
            device_config.systemAvailableFeature.append(lib)
        for lib in self.gl.extensions:
            device_config.glExtension.append(lib)
        return device_config


def parse_dict(v):
    if type(v) == dict:
        return DeviceConfig(v)
    elif type(v) == str:
        return f'"{v}"'
    else:
        return v

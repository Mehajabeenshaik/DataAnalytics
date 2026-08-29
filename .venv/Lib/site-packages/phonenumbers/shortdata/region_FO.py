"""Auto-generated file, do not edit by hand. FO metadata"""
from ..phonemetadata import NumberFormat, PhoneNumberDesc, PhoneMetadata

PHONE_METADATA_FO = PhoneMetadata(id='FO', country_code=None, international_prefix=None,
    general_desc=PhoneNumberDesc(national_number_pattern='1\\d{2,3}', possible_length=(3, 4)),
    toll_free=PhoneNumberDesc(national_number_pattern='1(?:1[24]|81\\d)', example_number='112', possible_length=(3, 4)),
    emergency=PhoneNumberDesc(national_number_pattern='11[24]', example_number='112', possible_length=(3,)),
    short_code=PhoneNumberDesc(national_number_pattern='11[248]|1(?:4[124]|71|8[17-9]|9\\d)\\d', example_number='112', possible_length=(3, 4)),
    sms_services=PhoneNumberDesc(national_number_pattern='19\\d\\d', example_number='1900', possible_length=(4,)),
    short_data=True)

""" Parse binary from RAW track 1. """
from typing import List, Any


def bitorder(str_hex: str) -> str:
    """ Convert a hexadecimal string to a binary within a string. """
    total = "".join(map(lambda ch: "{:04b}".format(int(ch, 16)), str_hex))
    return total


def reverse(str_bin: str) -> str:
    """ Reverse the binary string. """
    total = str_bin[::-1]
    return total


def chunks(string, n):
    """ Yield successive n-sized chunks from string. """
    for i in range(0, len(string), n):
        yield string[i:i + n]


def hexifyli(l: list):
    """ Convert a list of binary strings to their hex representations. """
    hex_l = []
    c = ''.join(l)
    binary_segments = [c[i:i + 7] for i in range(0, len(c), 7)]
    binary_segments = binary_segments[:-1]
    for segment in binary_segments:

        segment = segment[:-1]
        if len(segment) % 6 != 0:
            segment = '0' + segment
        hex_l.append(segment)

    hex_l = hex_l[:-1]
    return hex_l


def hexifystr(l: list):
    """ Convert a list of binary strings to their hex representations. """
    hex_str = ""

    for i in l:
        hex_str += format(int(i, 2), '02x')

    return hex_str


# def reverse_transform(eight_bit_rows):
#     combined = ''.join(eight_bit_rows)  # Combine all 8-bit rows into a single string
#     original_rows = []
#
#     # Extract every 7 bits as a new row from the combined string
#     for i in range(0, len(combined) - 1, 7):
#         original_row = combined[i:i + 7]
#         original_rows.append(original_row)
#
#     return original_rows


# def encode_string_to_6bit_binary(input_string):
#     """
#     Encodes a given ASCII string into a 6-bit binary format based on the provided mapping.
#     """
# Mapping of ASCII characters to 6-bit binary, inverse of RAW_t1_binary mapping
# ascii_to_binary = {
# ' ': '000000', '0': '000010', '@': '000001', 'P': '000011',
# '!': '100000', '1': '100010', 'A': '100001', 'Q': '100011',
# '"': '010000', '2': '010010', 'B': '010001', 'R': '010011',
# '#': '110000', '3': '110010', 'C': '110001', 'S': '110011',
# '$': '001000', '4': '001010', 'D': '001001', 'T': '001011',
# '%': '101000', '5': '101010', 'E': '101001', 'U': '101011',
# '&': '011000', '6': '011010', 'F': '011001', 'V': '011011',
# '\'': '111000', '7': '111010', 'G': '111001', 'W': '111011',
# '(': '000100', '8': '000110', 'H': '000101', 'X': '000111',
# ')': '100100', '9': '100110', 'I': '100101', 'Y': '100111',
# '*': '010100', ':': '010110', 'J': '010101', 'Z': '010111',
# '+': '110100', ';': '110110', 'K': '110101', '[': '110111',
# '`': '001100', '<': '001110', 'L': '001101', '\\': '001111',
# ',': '101100', '=': '101110', 'M': '101101', ']': '101111',
# '.': '011100', '>': '011110', 'N': '011101', '^': '011111',
# '/': '111100', '?': '111110', 'O': '111101', '_': '111111'
#     '000000': ' ', '000010': '0', '000001': '@', '000011': 'P',
#     '100000': '!', '100010': '1', '100001': 'A', '100011': 'Q',
#     '010000': '\"', '010010': '2', '010001': 'B', '010011': 'R',
#     '110000': '#', '110010': '3', '110001': 'C', '110011': 'S',
#     '001000': '$', '001010': '4', '001001': 'D', '001011': 'T',
#     '101000': '%', '101010': '5', '101001': 'E', '101011': 'U',
#     '011000': '&', '011010': '6', '011001': 'F', '011011': 'V',
#     '111000': '\'', '111010': '7', '111001': 'G', '111011': 'W',
#     '000100': '(', '000110': '8', '000101': 'H', '000111': 'X',
#     '100100': ')', '100110': '9', '100101': 'I', '100111': 'Y',
#     '010100': '*', '010110': ':', '010101': 'J', '010111': 'Z',
#     '110100': '+', '110110': ';', '110101': 'K', '110111': '[',
#     '001100': '`', '001110': '<', '001101': 'L', '001111': '\\',
#     '101100': ',', '101110': '=', '101101': 'M', '101111': ']',
#     '011100': '.', '011110': '>', '011101': 'N', '011111': '^',
#     '111100': '/', '111110': '?', '111101': 'O', '111111': '_'
#
# }
#
# # Convert the input string to binary from hex
# binary_string = bin(int(input_string, 16))[2:]
# print(binary_string)
# print(bin(int(input_string, 16))[2:8])
# # Split the binary string into 7-bit rows
# binary_rows = [binary_string[i:i + 7] for i in range(0, len(binary_string), 7)]
# # check if each row is in the mapping, if it is append mapping to encoded_binary if not continue
# encoded_binary = ''
# for row in binary_rows:
#     # row should only be the first 6 bits of the binary string
#     row = row[:6]
#     print(row)
#     if row in ascii_to_binary.keys():
#         print("in keys")
#         encoded_binary += ascii_to_binary.get(row)
#     else:
#         continue
#
# return encoded_binary


def reverse_transform(eight_bit_rows):
    # Combine all rows and then split them back into original format
    combined = ''.join(eight_bit_rows)
    original_rows = []
    start = 0

    for row in eight_bit_rows[:-1]:  # Exclude the last row in this loop
        # Find the end of the original row (excluding the last bit which is the start of the next row)
        end = start + len(row) - 1
        original_rows.append(combined[start:end])
        start = end

    # Handle the last row - it might not need to discard the last bit
    if len(eight_bit_rows[-1].rstrip('0')) % 8 == 0:  # If the last row is a full 8 bits before padding
        original_rows.append(eight_bit_rows[-1][:-1])
    else:
        original_rows.append(eight_bit_rows[-1].rstrip('0') + '0')

    return original_rows


# def bit_binary_to_str(input):
#     """
#     Converts a given hexadecimal string into ASCII characters using a 6-bit binary encoding.
#     """
#     asci_binary = {
#         '000000': ' ', '000010': '0', '000001': '@', '000011': 'P',
#         '100000': '!', '100010': '1', '100001': 'A', '100011': 'Q',
#         '010000': '\"', '010010': '2', '010001': 'B', '010011': 'R',
#         '110000': '#', '110010': '3', '110001': 'C', '110011': 'S',
#         '001000': '$', '001010': '4', '001001': 'D', '001011': 'T',
#         '101000': '%', '101010': '5', '101001': 'E', '101011': 'U',
#         '011000': '&', '011010': '6', '011001': 'F', '011011': 'V',
#         '111000': '\'', '111010': '7', '111001': 'G', '111011': 'W',
#         '000100': '(', '000110': '8', '000101': 'H', '000111': 'X',
#         '100100': ')', '100110': '9', '100101': 'I', '100111': 'Y',
#         '010100': '*', '010110': ':', '010101': 'J', '010111': 'Z',
#         '110100': '+', '110110': ';', '110101': 'K', '110111': '[',
#         '001100': '`', '001110': '<', '001101': 'L', '001111': '\\',
#         '101100': ',', '101110': '=', '101101': 'M', '101111': ']',
#         '011100': '.', '011110': '>', '011101': 'N', '011111': '^',
#         '111100': '/', '111110': '?', '111101': 'O', '111111': '_'
#
#     }
#     decoded_string = ''
#     print(input)
#     for i in input:
#         binary_string = bin(int(i, 16))[2:]
#         binary_segments = [binary_string[i:i + 7] for i in range(0, len(binary_string), 7)]
#
#         # Translate each 6-bit segment into an ASCII character
#
#         for segment in binary_segments:
#
#             segment = segment[:-1]
#             if len(segment) % 6 != 0:
#                 segment = '0' + segment
#             if segment in asci_binary:
#                 decoded_string += asci_binary[segment]
#
#     return decoded_string

def bit_binary_to_str(input):
    """
    Converts a given hexadecimal string into ASCII characters using a 6-bit binary encoding.
    """
    asci_binary = {
        '000000': ' ', '000010': '0', '000001': '@', '000011': 'P',
        '100000': '!', '100010': '1', '100001': 'A', '100011': 'Q',
        '010000': '\"', '010010': '2', '010001': 'B', '010011': 'R',
        '110000': '#', '110010': '3', '110001': 'C', '110011': 'S',
        '001000': '$', '001010': '4', '001001': 'D', '001011': 'T',
        '101000': '%', '101010': '5', '101001': 'E', '101011': 'U',
        '011000': '&', '011010': '6', '011001': 'F', '011011': 'V',
        '111000': '\'', '111010': '7', '111001': 'G', '111011': 'W',
        '000100': '(', '000110': '8', '000101': 'H', '000111': 'X',
        '100100': ')', '100110': '9', '100101': 'I', '100111': 'Y',
        '010100': '*', '010110': ':', '010101': 'J', '010111': 'Z',
        '110100': '+', '110110': ';', '110101': 'K', '110111': '[',
        '001100': '`', '001110': '<', '001101': 'L', '001111': '\\',
        '101100': ',', '101110': '=', '101101': 'M', '101111': ']',
        '011100': '.', '011110': '>', '011101': 'N', '011111': '^',
        '111100': '/', '111110': '?', '111101': 'O', '111111': '_'

    }
    decoded_string = ''
    hl = [input[i:i + 2] for i in range(0, len(input), 2)]
    for i in hl:
        binary_string = bin(int(i, 16))[2:]
        if len(binary_string) % 6 != 0:
            binary_string = '0' + binary_string
        if binary_string in asci_binary:
            decoded_string += asci_binary[binary_string]
    return decoded_string
# encoded_binary = encode_string_to_6bit_binary("A")
# print(encoded_binary)
##a=RAW_track1(encoded_binary)
# def binarystrtobin(binarystr):
#     # return a binary value interpreted from a string of binary
#     return int(binarystr, 2)

#test = "c5b07814954e3e2a"
#test = "c5b07814954e3e2a"
#test = "c5b07814954e3e2a"
#test = "c5b07814954e3e2a"
#test = "c5b07814954e3e2a"
test = "c5b07814954e3e2a"
print("Original Hex:", test)
binary_st = bitorder(test)
reversed_binary = reverse(binary_st)
chunks_list = list(chunks(reversed_binary, 8))
corrected_chunks = chunks_list[::-1]
hex_list = hexifyli(corrected_chunks)
og_hexstr = hexifystr(hex_list)
decoded_data = bit_binary_to_str(og_hexstr)
print(decoded_data)
# print(binarystrtobin(encoded_binary))
# e=binarystrtobin(encoded_binary)
# a=RAW_track1([e])
# print(type(e))
# a=RAW_track1([''0b100001])
# decoded_data = RAW_track1('28')
# print(decoded_data)
# en = bit_binary_to_str(['51', '43', '23', '62', '45', '25', '64', '7c'])
# print(en)
# test = "a30d1e28a9727c54"

# print("Binary:", binary_str)

# print("Reversed Binary:", reversed_binary)


# print("Corrected Chunks:", corrected_chunks)
graph = {
    '00001': '0',
    '10000': '1',
    '01000': '2',
    '11001': '3',
    '00100': '4',
    '10101': '5',
    '01101': '6',
    '11100': '7',
    '00010': '8',
    '10011': '9',
    '01011': ':',
    '11010': ';',
    '00111': '<',
    '10110': '=',
    '01110': '>',
    '11111': '?'
}

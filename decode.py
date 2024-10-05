import math
binary_to_char = {
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
t2_binary_to_char = {
    '0000': '0','1000': '1','0100': '2','1100': '3',
    '0010': '4','1010': '5','0110': '6','1110': '7',
    '0001': '8','1001': '9','0101': ':','1101': ';',
    '0011': '<','1011': '=','0111': '>','1111': '?'
}

# Function to split bitstring into parts of given lengths
def split_bitstring(bitstring, lengths):
    parts = []
    start = 0
    for length in lengths:
        parts.append(bitstring[start:start + length])
        start += length
    return parts

def fivernd(x):
    return math.ceil(x / 5) * 5

def decode(hex):
    first_value = int(hex[0], 16)
    print("first_value", first_value)
    #output_lengths = [7] * first_value + [1]
    shiftmod =((first_value-1) * 8)//7
    print("shiftmod", shiftmod)
    output_lengths = [7] * shiftmod + [1]
    #print(output_lengths)
    del hex[0]
    binary_data = [bin(int(h, 16))[2:].zfill(8) for h in hex]
    #print("binary_data", binary_data)
    print("length", len(binary_data))
    combined_bitstring = ''.join(binary_data)
    print("combined length", len(combined_bitstring))
    # Split the combined bitstring according to the desired lengths
    output_binaries = split_bitstring(combined_bitstring, output_lengths)
    print("output bin length", len(output_binaries))
    print("output_binaries", output_binaries)
    print("")
    # remove the zero padding at the end
    del output_binaries[-1]
    # remove the lrc byte
    del output_binaries[-1]
    print("output_binaries",output_binaries)
    #print("output_lengths",output_binaries)
    # Extract data bits (first 6 bits) 7th bit is parity bit
    data_bits = [b[:6] for b in output_binaries]

    # Convert the 6-bit data to characters using the provided encoding table
    decoded_characters = [binary_to_char[b] for b in data_bits]

    # Join the characters to form the decoded string
    decoded_string = ''.join(decoded_characters)
    return decoded_string



def decode2(hex):
    first_value = int(hex[0], 16)
    print("first_value", first_value)
    shiftmod= fivernd((first_value-1) * 8)//5
    print("shiftmod",shiftmod)
    output_lengths = [5] * shiftmod
    del hex[0]
    binary_data = [bin(int(h, 16))[2:].zfill(8) for h in hex]
    combined_bitstring = ''.join(binary_data)
    output_binaries = split_bitstring(combined_bitstring, output_lengths)
    del output_binaries[-1]
    data_bits = [b[:4] for b in output_binaries]
    decoded_characters = [t2_binary_to_char[b] for b in data_bits]
    decoded_string = ''.join(decoded_characters)
    return decoded_string

decoded_string2 = decode(["09","A3", "0D", "1E", "28", "A9", "72", "7C", "54"])
print(f'{decoded_string2}\n')
decoded_string3 = decode2(["06","D4", "11", "92", "57", "F5"])
print(f'{decoded_string3}\n')


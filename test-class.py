
class Packet:
    def __init__(self, hex_list):
        self.hex_list = hex_list
        self.track1_data = []
        self.track2_data = []
        self.track3_data = []
        self.parse_packet()

    def find_track_data(self, start_index, end_marker):
        try:
            end_index = self.hex_list.index(end_marker[0], start_index + 1)
            if self.hex_list[end_index:end_index + len(end_marker)] == end_marker:
                return self.hex_list[start_index:end_index]
            return []
        except ValueError:
            return []

    def parse_packet(self):
        try:
            # Find track 1 data
            track1_marker = [0x1b, 0x73, 0x1b, 0x1]
            track1_start_index = self.find_start_index(track1_marker)
            if track1_start_index is not None:
                self.track1_data = self.find_track_data(track1_start_index + len(track1_marker), [0x1b])
    
            # Find track 2 data
            track2_marker = [0x1b, 0x2]
            track2_start_index = self.find_start_index(track2_marker, track1_start_index + len(track1_marker))
            if track2_start_index is not None:
                self.track2_data = self.find_track_data(track2_start_index + len(track2_marker), [0x1b])

            # Find track 3 data
            track3_marker = [0x1b, 0x3]
            track3_start_index = self.find_start_index(track3_marker, track2_start_index + len(track2_marker))
            if track3_start_index is not None:
                self.track3_data = self.find_track_data(track3_start_index + len(track3_marker), [0x3f, 0x1c, 0x1b])
        except ValueError:
            pass

    def find_start_index(self, marker, start=0):
        try:
            for i in range(start, len(self.hex_list) - len(marker) + 1):
                if self.hex_list[i:i + len(marker)] == marker:
                    return i
        except ValueError:
            return None
        return None

    def __repr__(self):
    # we want to return each track as a list of hex strings
    # so we convert each byte to a hex string and then join them
        track1 = [hex(x) for x in self.track1_data]

        track2 = [hex(x) for x in self.track2_data]
        track3 = [hex(x) for x in self.track3_data]
        return (f"Packet(\n  track1_data={track1},\n  track2_data={track2},\n" f"  track3_data={track3}\n)")


        #return (f"Packet(\n  track1_data={self.track1_data},\n  track2_data={self.track2_data},\n"
    #    f"  track3_data={self.track3_data}\n)")

# Example usage
hex_list =['de', '1b', '73', '1b', '1', '9', 'a3', '0d', '1e', '28', 'a9', '72', '7c', '54', '00', '1b', '2', '6', 'd4', '11', '92', '57', 'f5', '00', '1b', '3', '0', '3f', '1c', '1b', '30']

hex_list = [int(x, 16) for x in hex_list]

packet = Packet(hex_list)
#convert back to list of strings and then hex strings



print(packet)


from datetime import date, time
from typing import List


def prettify_time(time: time):
    return time.strftime("%#I:%M %p")


def prettify_date(date: date):
    return date.strftime("%#m/%#d/%#y")


def pretty_print_table(table: List[List[str]], file=None):
    if not table:
        return

    num_rows = len(table)
    num_cols = len(table[0])

    col_sizes = []
    for col in range(num_cols):
        longest_len_word_in_col = 0
        for row in range(num_rows):
            word = str(table[row][col])
            longest_len_word_in_col = max(longest_len_word_in_col, len(word))
        col_sizes.append(longest_len_word_in_col)

    row_template = ""
    for size in col_sizes:
        row_template += " {:" + str(size) + "} "

    for row in table:
        str_row = map(str, row)
        print(row_template.format(*str_row), file=file)

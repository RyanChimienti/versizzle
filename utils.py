from datetime import date, time


def prettify_time(time: time):
    return time.strftime("%#I:%M")


def prettify_date(date: date):
    return date.strftime("%#m/%#d/%#y")
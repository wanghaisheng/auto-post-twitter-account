from datetime import datetime, timedelta, date
import numpy as np
import os
import pandas as pd
import requests
import seaborn as sns
import sys
import time

from scripts.utils.twitter import post_media, post_media_update
from scripts.utils.dataframes import update_csv, get_csv
from scripts.utils.github import update_no_app
from scripts.utils.sms import call_sms
from scripts.appointments_op import get_appointment_data

today = date.today()
TODAYS_DATE_IS = today.strftime("%d/%m/%Y")
MAIN_URL = 'https://www.passport.service.gov.uk/urgent/'
SERVICE = "premium"
IS_PROXY = False
IS_GITHUB_ACTION = True
IS_TWITTER = True
wait_mins = 10
number_of_appointments_classed_as_bulk = 5


def check_diff_in_loc_counts(df):
    """
    Checks the difference in the counts of appointments at each office, if an office has 10 or more new appointments
    then the bot will flag this to be posted to Twitter

    Args:
        df: pd.DataFrame
            The pandas dataframe of the latest results

    Returns:
        locations_added: list
            List of offices with new appointments added, is blank if None
    """

    org = "mshodge"
    repo = "youshallnotpassport"
    branch = "main"
    file_path = "data/premium_appointments_cal.csv"

    csv_url = f'https://raw.githubusercontent.com/{org}/{repo}/{branch}/{file_path}'

    df_old = pd.read_csv(csv_url)

    dates_in_both = [i for i, j in zip(df_old.columns, df.columns) if i == j]
    dates_in_both.remove('location')

    locations_added = []

    for date_in_both in dates_in_both:
        diff_series = df[date_in_both] - df_old[date_in_both]
        for _, val in diff_series.iteritems():
            if val > number_of_appointments_classed_as_bulk:
                if df.loc[_,'location'] not in locations_added:
                    locations_added.append(df.loc[_,'location'])

    return locations_added


def run_github_action(id):
    """
    Returns value from dataframe

    Args:
        id: str
            The workflow id for GitHub actions
        github_action: Bool
            If using GitHub actions or not
    """

    token = os.environ['access_token_github']
    url = f"https://api.github.com/repos/mshodge/youshallnotpassport/actions/workflows/{id}/dispatches"
    headers = {"Authorization": "bearer " + token}
    json = {"ref": "main"}
    r = requests.post(url, headers=headers, json=json)
    print(r)


def check_if_no_apps_before():
    """
    Checks if the bot has already seen a return of no appointments in the table already today

    Returns:
        no_app_check_date: str
            The date checked last
        no_appointment_check_result: str
            The result checked last
    """

    no_appointment_check = requests.get(
        "https://raw.githubusercontent.com/mshodge/youshallnotpassport/main/data/premium_no_apps.md").text \
        .replace("\n", "").split(" ")
    no_appointment_check_date = no_appointment_check[0]
    no_appointment_check_result = no_appointment_check[1]
    return no_appointment_check_date, no_appointment_check_result


def long_dataframe(wide_df):
    """
    Make a long dataframe

    Args:
        wide_df: pd.dataframe
            The pandas dataframe in wide format

    Returns:
        long_df: pd.dataframe
            The pandas dataframe in long format
    """

    wide_df['location'] = wide_df.index
    long_df = pd.melt(wide_df, id_vars="location")
    long_df.columns = ["location", "appt_date", "count"]

    timestamp = datetime.now()
    timestamp = timestamp.strftime("%d/%m/%Y")

    long_df["scrape_date"] = timestamp

    return long_df


def nice_dataframe(not_nice_df):
    """
    Makes a nice dataframe

    Args:
        not_nice_df: pd.dataframe
            The pandas dataframe that is not nicely formatted

    Returns:
        df: pd.dataframe
            A nicely formatted pandas dataframe
    """

    base = datetime.today()
    date_list = [(base + timedelta(days=x)).strftime("%A %-d %B") for x in range(28)]
    better_date_list = [(base + timedelta(days=x)).strftime("%a %-d %b") for x in range(28)]

    nice_df = pd.DataFrame(columns=date_list,
                           index=["London", "Peterborough", "Newport", "Liverpool", "Durham", "Glasgow", "Belfast",
                                  "Birmingham"])

    not_nice_df.columns = not_nice_df.columns.str.replace("  ", " ")

    not_nice_df = not_nice_df.reset_index()
    for col in list(not_nice_df.columns):
        for idx in not_nice_df.index:
            location = not_nice_df.iloc[idx]["index"]

            number_of_appointments = not_nice_df.iloc[idx][col]
            nice_df.at[location, col] = number_of_appointments

    nice_df = nice_df.drop(columns=['index'])
    nice_df.columns = better_date_list

    nice_df = nice_df.fillna(0)
    nice_df = nice_df.astype(float)
    return nice_df


def make_figure(the_df):
    """
    Makes a seaborn heatmap figure from appointments dataframe

    Args:
        the_df: pd.dataframe
            The pandas dataframe
    """

    days_list = list(range(0, 10))
    days_list2 = list(range(10, 28))
    the_df[the_df.eq(0)] = np.nan
    appointments = sns.heatmap(the_df, annot=True,
                               cbar=False, cmap="Oranges", linewidths=1, linecolor="white",
                               vmin=0, vmax=30, annot_kws={"fontsize": 8})

    appointments.set_title("The number of Premium appointments \n\n")
    for i in range(len(days_list)):
        appointments.text(i + 0.3, -0.1, str(days_list[i]), fontsize=8)
    for i in range(len(days_list2)):
        appointments.text(i + 10.1, -0.1, str(days_list2[i]), fontsize=8)

    appointments.figure.tight_layout()
    appointments.text(10, -0.5, "(Days from Today)", fontsize=10)
    fig = appointments.get_figure()
    fig.savefig("out.png")


def pipeline(first=True):
    """
    The main function to get the appointment data from the table at the end of the process

    Args:
        first: Bool
            The first run after the service has gone online?
    """

    print(f"Is first time running since going online: {first}")

    if "Sorry" in requests.get("https://www.passport.service.gov.uk/urgent/").text:
        print("It's offline!")
    else:
        try:
            nice_appointments_df = get_appointment_data(MAIN_URL, IS_GITHUB_ACTION)
        except ValueError:
            if first:
                run_github_action("28968845") if IS_GITHUB_ACTION else None
            else:
                run_github_action("32513748") if IS_GITHUB_ACTION else None
            raise Exception('Error. Failed to get the appointments table.')

        if nice_appointments_df is None:
            time.sleep(wait_mins * 60)  # wait 2 mins before calling again
            run_github_action("32513748") if IS_GITHUB_ACTION else None
            raise Exception(f"Error. Appointments table returned was none. Will try again in {wait_mins} minutes.")

        print(nice_appointments_df)

        appointments_per_location = nice_appointments_df.sum(axis=1).to_frame().reset_index()
        appointments_per_location.columns = ['location', 'count']

        cal_df = nice_appointments_df.reset_index().rename(columns={'index': 'location'})

        if first is False:
            locs_added_checked = check_diff_in_loc_counts(appointments_per_location)

        failed = update_csv(cal_df, IS_GITHUB_ACTION,
                            "data/premium_appointments_cal.csv",
                            "updating premium appointment cal data", replace=True)

        if failed:
            run_github_action("32513748")
            raise Exception(f"Error. Failed to return the GitHub file. Will try again.")

        if first is False:
            if len(locs_added_checked) == 0:
                print(f"No new bulk appointments added. Will check again in {wait_mins} minutes.")
                time.sleep(wait_mins * 60)  # wait 2 mins before calling again
                run_github_action("32513748") if IS_GITHUB_ACTION else None
                return None
        else:
            locs_added_checked = []

        make_figure(nice_appointments_df)
        if IS_TWITTER and first:
            post_media(IS_PROXY, IS_GITHUB_ACTION, SERVICE)
            update_no_app(IS_GITHUB_ACTION, TODAYS_DATE_IS, SERVICE, "False")

        # Posts a graph if new appointments have been added
        if IS_TWITTER and len(locs_added_checked) > 0:
            message = post_media_update(IS_PROXY, IS_GITHUB_ACTION, locs_added_checked, SERVICE)
            call_sms(SERVICE.title(), type="app", response=message)
            update_no_app(IS_GITHUB_ACTION, TODAYS_DATE_IS, SERVICE, "False")

        long_appointments_df = long_dataframe(nice_appointments_df)
        failed = update_csv(long_appointments_df, IS_GITHUB_ACTION,
                            "data/premium_appointments.csv",
                            "updating premium appointment data", replace=False)
        time.sleep(wait_mins * 60)  # wait 3 mins before calling again
        print(f"Successfully found new appointments, will check again in {wait_mins} minutes")
        run_github_action("32513748") if IS_GITHUB_ACTION else None


if __name__ == "__main__":
    if sys.argv[1:][0] == 'True':
        is_first = True
    else:
        is_first = False

    pipeline(first=is_first)

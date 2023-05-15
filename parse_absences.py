import sys

from bs4 import BeautifulSoup
import dateparser

from errors import log_message, log_error_message, get_stack_trace


# From https://absences2.epfl.ch/home/plannings
# save as HTML - full page from Firefox => should be a few hundred KBs (+ one subfolder we don't need)

vacation = ('Vacances', 'Holidays', 'Compensation sur heures', 'Compensation - on hours')


def get_all_text(node):
    if node.nodeType == node.TEXT_NODE:
        return node.text
    else:
        text_string = ""
        for child_node in node.childNodes:
            text_string += get_all_text(child_node)
    return text_string


def list_divs(node, ntabs=0):
    all_subdivs = node.find_all('div')
    subdivs = [div for div in all_subdivs if len(div.find_all('div')) > 0]
    for subdiv in subdivs:
        list_divs(subdiv, ntabs=ntabs+1)
    log_message('\t'*ntabs + f'{len(subdivs)} subdivs')


def parse_absences(htmlfile):
    HTMLFile = open(htmlfile, "r")
    index = HTMLFile.read()

    S = BeautifulSoup(index, 'lxml')
    try:
        log_message('parse_absences')
        tables = S.find_all('table')
        log_message(f'Found {len(tables)} tables in the page.')

        for idx, t in enumerate(tables):
            subtables = t.find_all('table')
            rows = t.find_all('tr')
            log_message(f'Table {idx} has {len(rows)} rows and contains {len(subtables)} sub-tables')
            log_message(f"Is FV there? {t.decode_contents().find('Varrato')}")
            log_message("Is Holidays there? {t.decode_contents().find('Holidays')}")
            for ridx, r in enumerate(rows):
                cols = r.find_all('td')
                if len(cols) == 1:
                    if get_all_text(cols[0]) is None:
                        log_message('Weird column:')
                    else:
                        pass
                else:
                    log_message(f'\tRow {ridx} has {len(cols)} columns')
            if 'fc-scrollgrid-sync-table' in t.get('class'):
                log_message(f"{[x.strip() for x in t.get('style').split(';') if x.find(':') > 0]}")
                styles = {k.split(':')[0].strip(): k.split(':')[1].strip() for k in [x.strip() for x in t.get('style').split(';') if x.find(':') > 0]}
                log_message(f'{styles}')
                if 'min-width' in styles:
                    total_width = styles['min-width']
                    log_message(f'Total absence table width {total_width}')

        log_message('---------')
        people_table = tables[3]
        log_message(f"Is FV really in there? {people_table.decode_contents().find('Varrato')}")
        people_rows = people_table.find_all('tr')
        librarians = [get_all_text(row).strip() for row in people_rows]

        fcDayThs = [th for th in S.find_all('th', class_='fc-day') if th.get('colspan') == '1']
        for th in fcDayThs:
            log_message(f"{[th.get('colspan')]}, {get_all_text(th)}, {th.get('data-date')}")
        known_days = [th.get('data-date') for th in fcDayThs]
        fcDayTds = S.find_all('td', class_='fc-day')
        log_message(f'Found {len(fcDayTds)} days')
        fcDayTds = S.find_all('td', class_='fc-day')

        absence_table = tables[5]
        
        if 'fc-scrollgrid-sync-table' in absence_table.get('class'):
            style_list = [x.strip() for x in absence_table.get('style').split(';') if x.find(':') > 0]
            styles = {k.split(':')[0].strip(): k.split(':')[1].strip() for k in style_list}
            log_message(f'{styles}')
            if 'min-width' in styles:
                total_width = styles['min-width']
                log_message(f"Total absence table width {int(total_width.replace('px', ''))}")
                day_width = int(total_width.replace('px', '')) // len(fcDayTds)
                log_message(f'One day should be {day_width} pixels')

        absence_rows = absence_table.find_all('tr')
        for ridx, row in enumerate(absence_rows):
            cells = row.find_all('td')
            log_message(f'{len(cells)}')
            if (len(cells) > 0):
                log_message(f'{cells[0].class_}')
                #print(cells[0].decode_contents())
                all_divs = cells[0].find_all('div')
                inner_divs = [div for div in all_divs if len(div.find_all('div')) == 0]
                events = [div for div in all_divs if 'fc-timeline-event-harness' in div.get('class')]
                log_message(f'{len(events)} events')
                log_message(f"{librarians[ridx]}, {len(inner_divs)}, {[(div.get('class'), get_all_text(div).strip(), div.get('style')) for div in events]}")
                for event in events:
                    event_style_list = [x.strip() for x in event.get('style').split(';') if x.find(':') > 0]
                    styles = {k.split(':')[0].strip(): k.split(':')[1].strip() for k in event_style_list}
                    start = int(styles['left'].replace('px', '')) // day_width
                    end = abs(int(styles['right'].replace('px', ''))) // day_width - 1
                    log_message(f'{librarians[ridx]} is off due to {get_all_text(event).strip()} from {known_days[start]} to {known_days[end]}')

    except IndexError as e:
        log_error_message('no table found?')
        log_error_message(get_stack_trace(e))
    except Exception as e:
        log_error_message('Something went really wrong')
        log_error_message(get_stack_trace(e))


if __name__ == "__main__":
    if len(sys.argv) > 1:
        htmlfile = sys.argv[1]
    else:
        htmlfile = "absences.html"

    output = parse_absences(htmlfile)

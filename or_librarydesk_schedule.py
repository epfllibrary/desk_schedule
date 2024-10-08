#!/usr/bin/env python
#-*- coding: utf-8 -*-

from ortools.sat.python import cp_model
import numpy
from numpy import array
import itertools
import argparse
from datetime import datetime, timedelta
import dateparser
import json

from inspect import currentframe, getframeinfo

from errors import log_message, log_error_message, get_stack_trace


# TODO if actually useful, this should be part of the input file...

sector_semester_quotas = {
    'SOAR': 5,
    'AIR': 2,
    'CUBA': 2,
    'SPICE': 1,
    'USEP': 1

}


def main(parameter_file, log_output, error_output):
    # This program tries to find an optimal assignment of librarians to shifts
    # (initially 10 shifts per day for 5 days), subject to various constraints.
    # Each librarian can request a personal schedule, shifts will be assigned
    # accordingly.
    # The optimal assignment maximizes the number of fulfilled shift requests.

    if parameter_file == '':
        from work_schedule import librarians, shift_requests, meeting_slots
        from work_schedule import quota, locations, rules, weekdays
        from work_schedule import desk_shifts, msg
    elif parameter_file is not None:
        from read_work_schedule import read_work_schedules, check_minima
        shift_requests, librarians, locations, quota, meeting_slots, rules, weekdays, desk_shifts = read_work_schedules(parameter_file, log_output, error_output)
        msg = check_minima(log_output, error_output, shift_requests, librarians, locations, quota, meeting_slots, rules, weekdays, desk_shifts)
    else:
        from read_work_schedule import read_work_schedules, check_minima
        filename = 'Horaires-guichets.xlsx'
        log_output = filename.replace('.xlsx', '') + '_log.txt'
        error_output = filename.replace('.xlsx', '') + '_errors.txt'
        shift_requests, librarians, locations, quota, meeting_slots, rules, weekdays, desk_shifts = read_work_schedules(filename, 'desk_schedule_log.txt', 'desk_schedule_errors.txt')
        msg = check_minima(log_output, error_output, shift_requests, librarians, locations, quota, meeting_slots, rules, weekdays, desk_shifts)

    diagnostics = msg

    num_shifts = len(desk_shifts)
    shift_starts = [x[0] for x in desk_shifts]
    num_locations = len(locations.keys())
    num_librarians = len(librarians.keys())
    num_days = len(weekdays.keys())

    all_librarians = range(num_librarians)
    all_shifts = range(num_shifts)
    all_days = range(num_days)
    all_locations = range(num_locations)

    # Maximum normal shift, the last one was special in the old shift model
    max_shift = num_shifts
    diagnostics += f' \n<br/>rules: {rules} <br/>\n'

    if rules['ScaleQuotas']:
        scale = num_days // 5
        diagnostics += f'quotas will be scaled by an integer factor of {scale} (num_days = {num_days})<br/>\n'
        for category in quota:
            quota[category] = (quota[category][0] * scale,
                               quota[category][1] * scale,
                               quota[category][2] * scale)
    else:
        scale = 1

    # Diagnostics: compate the sum of minimal quotas and the total amount of shifts to fill
    minimum_quotas = sum([quota[librarians[n]['type']][1] for n in all_librarians])
    maximum_quotas = sum([quota[librarians[n]['type']][0] for n in all_librarians])
    total_shifts = num_days * num_shifts * num_locations
    diagnostics += f'Shift count: max {maximum_quotas}, min {minimum_quotas}, total {total_shifts}<br/>'
    if (total_shifts < minimum_quotas) or (total_shifts > maximum_quotas):
        diagnostics += 'Your quotas cannot be met with the proposed shifts, remember to skip a few quota rules!<br/>'

    log_message(log_output, diagnostics)

    # Creates the model.
    model = cp_model.CpModel()
    v0 = model.NewBoolVar("buggyVarIndexToVarProto")
    # model.VarIndexToVarProto(0) always returns the last created variable...?

    # Let's see how many conditions we define
    n_conditions = 0

    # Creates shift variables.
    # shifts[(n, d, s, lo)]: 
    # librarian 'n' works shift 's' on day 'd' at location lo.
    shifts = {}
    for n in all_librarians:
        for d in all_days:
            for s in all_shifts:
                for lo in all_locations:
                    shifts[(n, d, s, lo)] = \
                        model.NewBoolVar('shift_n%id%is%ilo%i' % (n, d, s, lo))

    if rules['useAbsences']:
        try:
            vacation = json.loads(open('vacation.json', 'r').read())
        except:
            log_error_message(error_output, 'useAbsences rule selected but no vacation.json file found => ignoring directive')
            vacation = {}
        absence_names = vacation.keys()
        input_names = [librarians[n]["name"] for n in all_librarians]
        no_vacation_names = [name for name in input_names if name not in absence_names]
        for name in no_vacation_names:
            log_message(log_output, f'(WARNING: {name} has no vacation days, maybe check for possible name mismatch?')

        for n in all_librarians:
            if librarians[n]["name"] not in vacation:
                vacation[librarians[n]['name']] = []
    else:
        vacation = {}
        for n in all_librarians:
            vacation[librarians[n]['name']] = []

    frameinfo = getframeinfo(currentframe())
    log_message(log_output, f'({frameinfo.filename}:{frameinfo.lineno + 1}) Vacation days: {vacation}')

    ## TODO integration vacation data into shift_requests
    for n in all_librarians:
        for d in all_days:
            desk_day = dateparser.parse(weekdays[d])
            # QUICKFIX make sure week days are in the current week if no specific dates are given
            if desk_day < dateparser.parse('Sunday'):
                desk_day += timedelta(days=7)
            frameinfo = getframeinfo(currentframe())
            log_message(log_output, f'({frameinfo.filename}:{frameinfo.lineno + 1}) {weekdays[d]} is {desk_day}')
            for leave in vacation[librarians[n]['name']]:
                frameinfo = getframeinfo(currentframe())
                log_message(log_output, f"({frameinfo.filename}:{frameinfo.lineno + 1}) {librarians[n]['name']} on vacation: {leave}")
                # FIXME this doesn't really work for 1-day leaves. F
                if (desk_day >= dateparser.parse(leave[0]) - + timedelta(minutes=1)) and \
                        (desk_day <= dateparser.parse(leave[1]) + timedelta(minutes=1)):
                    frameinfo = getframeinfo(currentframe())
                    log_message(log_output, f'({frameinfo.filename}:{frameinfo.lineno + 1}) {librarians[n]} must not work on {weekdays[d]}')
                    for s in all_shifts:
                        for lo in all_locations:
                            # TESTING this could be it
                            shift_requests[n][d][s][lo] = 0
                            pass

    if rules['oneLibrarianPerShift']:
        oneLibrariaPerShift = model.NewBoolVar('oneLibrarianPerShift')
        # Each shift at each location is assigned to exactly 1 librarian
        for d in all_days:
            for s in all_shifts:
                for lo in all_locations:
                    if s < locations[lo]['times'][d]['start'] or s > locations[lo]['times'][d]['end']:
                        model.Add(sum([shifts[(n, d, s, lo)] for n in all_librarians]) == 0).OnlyEnforceIf(oneLibrariaPerShift)
                        n_conditions += 1
                    elif s == all_shifts[-1] and (d == all_days[-1]):
                        model.Add(sum([shifts[(n, d, s, lo)] for n in all_librarians]) == 0).OnlyEnforceIf(oneLibrariaPerShift)
                        n_conditions += 1
                    else:
                        model.Add(sum([shifts[(n, d, s, lo)] for n in all_librarians]) == 1).OnlyEnforceIf(oneLibrariaPerShift)
                        n_conditions += 1 
        model.Proto().assumptions.append(oneLibrariaPerShift.Index())

    if rules['oneShiftAtATime']:
        # Each librarian is using at most 1 seat at a time!
        oneShiftAtATime = model.NewBoolVar('oneShiftAtATime')
        for d in all_days:
            for s in all_shifts:
                for n in all_librarians:
                    model.Add(sum([shifts[(n, d, s, lo)] for lo in all_locations]) <= 1).OnlyEnforceIf(oneShiftAtATime)
                    n_conditions += 1 
        model.Proto().assumptions.append(oneShiftAtATime.Index())

    if rules['maxTwoShiftsPerDay']:
        # Each librarian works at most max_shifts_per_day=2 hours per day.
        # TODO: mix Accueil and STM shifts over the week?
        # TESTING Should still work with non-1h shifts, but probably not applicable in that case
        max_shifts_per_day = 2
        maxTwoShiftsPerDay = model.NewBoolVar('maxTwoShiftsPerDay')
        for n in all_librarians:
            for d in all_days:
                model.Add(sum([shifts[(n, d, s, lo)]
                    for s in all_shifts for lo in all_locations]) <= max_shifts_per_day)
                n_conditions += 1
        model.Proto().assumptions.append(maxTwoShiftsPerDay.Index())

    if rules['maxOneShiftPerDay']:
        max_shifts_per_day = 1
        # Each librarian works at most max_shifts_per_day=1 shifts per day.
        maxOneShiftPerDay = model.NewBoolVar('maxOneShiftsPerDay')
        for n in all_librarians:
            for d in all_days:
                model.Add(sum([shifts[(n, d, s, lo)]
                    for s in all_shifts for lo in all_locations]) <= max_shifts_per_day)
                n_conditions += 1
        model.Proto().assumptions.append(maxOneShiftPerDay.Index())

    if rules['minOneShiftAverage']:
        min_average_shifts = num_days // 5
        # Each librarian works at at least min_average_shifts=1 shifts per week/over the period.
        minOneShiftAverage = model.NewBoolVar('minOneShifAtverage')
        for n in all_librarians:
            if quota[librarians[n]['type']][0] > 0:
                    model.Add(sum([shifts[(n, d, s, lo)]
                        for s in all_shifts for lo in all_locations for d in all_days]) >= min_average_shifts)
                    n_conditions += 1
            else:
                log_message(log_output, f'{librarians[n]["name"]} is exempted from minimum av. shifts')
        model.Proto().assumptions.append(minOneShiftAverage.Index())

    delta_vars1 = {}
    delta_vars2 = {}
    # TODO: Perhaps not valid if we switch to 2h shifts, or 2.5, or 3?
    # Probably not applicable in that case anyway
    for n in all_librarians:
        if librarians[n]['prefered_length'] > 1:
            for d in all_days:
                for s in all_shifts[0:-1]:
                    delta_vars1[(n, d, s)] = \
                        model.NewIntVar(-1, 1, 'tmp1deltan%id%is%i' % (n, d, s))
                    delta_vars2[(n, d, s)] = \
                        model.NewIntVar(0, 1, 'tmp2deltan%id%is%i' % (n, d, s)) 
    if rules['preferedRunLength']:        
        # FIXME: 2 SUCCESSIVE shifts if requested
        # NOTE: current version seems to favor same-day shifts but not successive?
        preferedRunLength = model.NewBoolVar('preferedRunLength')
        for n in all_librarians:
            if librarians[n]['prefered_length'] > 1: 
                for d in all_days:
                    # Successive shifts preference?
                    # The number of changes from "busy" to "free" or back describes
                    # the number of discontinuous shifts
                    # somthing like sum(abs(shifts[(n, d, s+1, lo)]-shifts[(n, d, s, lo)]))
                    for s in all_shifts[0:-1]:
                        model.Add(sum([shifts[(n, d, s+1, lo)]-shifts[(n, d, s, lo)]
                            for lo in all_locations]) == delta_vars1[(n, d, s)])
                        model.AddAbsEquality(delta_vars2[(n, d, s)], delta_vars1[(n, d, s)])
                    model.Add(sum([delta_vars2[(n, d, s)] for s in all_shifts[0:-1]])*librarians[n]['prefered_length'] <= 2*sum([shift_requests[n][d][s][lo] * shifts[(n, d, s, lo)]
                        for lo in all_locations for s in all_shifts])).OnlyEnforceIf(preferedRunLength)
                    n_conditions += 1

        model.Proto().assumptions.append(preferedRunLength.Index())
        
    if rules['maxOneLateShift']:
        # only assign max. one 18-20 shift for a given librarian
        # TESTING: should valid if we switch to 2h shifts, or 2.5, or 3?
        maxOneLateShift = model.NewBoolVar('maxOneLateShift')
        s = all_shifts[-1]
        for n in all_librarians:
            model.Add(sum([shifts[(n, d, s, lo)]
                for d in all_days for lo in all_locations]) <= 1).OnlyEnforceIf(maxOneLateShift)
            n_conditions += 1
        model.Proto().assumptions.append(maxOneLateShift.Index())

    if rules['noSeventeenToTwenty']:
        # prevent 17-18 + 18-20 sequence for any librarian
        # TESTING should still be working using non-1h shifts
        noSeventeenToTwenty = model.NewBoolVar('noSeventeenToTwenty')
        for n in all_librarians:
            for d in all_days:
                model.Add(sum([shifts[(n, d, s, lo)]
                    for s in all_shifts[-2:] for lo in all_locations]) <= 1).OnlyEnforceIf(noSeventeenToTwenty)
                n_conditions += 1
        model.Proto().assumptions.append(noSeventeenToTwenty.Index())

    if rules['noTwelveToFourteen']:
        # TESTING: should work with non-1h slots, just inoperative for 2h slots
        # prevent 12-13 + 13-14 sequence for any librarian
        noTwelveToFourteen = model.NewBoolVar('noTwelveToFourteen')
        critical_zone_minutes = [max([x for x in shift_starts if x <= 12*60]),
                                 min([x for x in shift_starts if x >= 14*60])]
        critical_zone_slots = [shift_starts.index(c) for c in critical_zone_minutes]
        for n in all_librarians:
            for d in all_days:
                model.Add(sum([shifts[(n, d, s, lo)]
                    for s in critical_zone_slots for lo in all_locations]) <= 1).OnlyEnforceIf(noTwelveToFourteen)
                n_conditions += 1
        model.Proto().assumptions.append(noTwelveToFourteen.Index())

    if rules['maxDaysAtDesk']:
        maxDaysAtDesk = model.NewBoolVar('maxDaysAtDesk')
        # daily_desk = {}
        day_at_desk = {}
        for n in all_librarians:
            for d in all_days:
                # daily_desk[(n, d)] = model.NewIntVar(0, 24, 'dailydesk_n%id%i' % (n, d))
                day_at_desk[(n, d)] = model.NewIntVar(0, 1, 'dayatdesk_n%id%i' % (n, d))
        #for n in all_librarians:
        for n in all_librarians:
            for d in all_days:
                model.AddMaxEquality(day_at_desk[(n, d)], [shifts[(n, d, s, lo)] for s in all_shifts for lo in all_locations])
            model.Add(sum([day_at_desk[(n, d)] for d in all_days]) <= quota[librarians[n]['type']][2])
            
        model.Proto().assumptions.append(maxDaysAtDesk.Index())

    # Try to distribute the shifts evenly, so that each librarian works
    # his quota of shifts (or quota - 1) on the active or reserve locations

    noOutOfTimeShift = model.NewBoolVar('noOutOfTimeShift')
    
    # TODO: is this still valid if we switch to 2h shifts, or 2.5, or 3?
    for n in all_librarians:
        num_hours_worked = 0
        num_hours_reserve = 0
        out_of_time_shifts = 0
        for d in all_days:
            # run_length = 0
            for s in all_shifts:
                for lo in all_locations:
                    if locations[lo]['name'].lower().find('remplacement') < 0:
                        num_hours_worked += shifts[(n, d, s, lo)]*int(desk_shifts[s][1]/60)
                    else:
                        num_hours_reserve += shifts[(n, d, s, lo)]*int(desk_shifts[s][1]/60)
                    out_of_time_shifts += shifts[(n, d, s, lo)] * (1-shift_requests[n][d][s][lo])
                    # Shifts during mandatory meetings also count as out of time
                    if dateparser.parse(weekdays[d]).weekday() == meeting_slots[librarians[n]['sector']][0]:
                        if s >= meeting_slots[librarians[n]['sector']][1] and s <= meeting_slots[librarians[n]['sector']][2]:
                            out_of_time_shifts += shifts[(n, d, s, lo)] * 1
                    if dateparser.parse(weekdays[d]).weekday() == meeting_slots['dir'][0] and librarians[n]['type'] == 'dir':
                        if s >= meeting_slots['dir'][1] and s <= meeting_slots['dir'][2]:
                            out_of_time_shifts += shifts[(n, d, s, lo)] * 1
                    
        if rules['noOutOfTimeShift']:        
            model.Add(out_of_time_shifts < 1).OnlyEnforceIf(noOutOfTimeShift)
            n_conditions += 1
        if rules['minActiveShifts']:
            minActiveShifts = model.NewBoolVar('minActiveShifts')
            model.Add(num_hours_worked >= quota[librarians[n]['type']][0] - quota[librarians[n]['type']][0]//2 ).OnlyEnforceIf(minActiveShifts)
            model.Proto().assumptions.append(minActiveShifts.Index())
            n_conditions += 1
        if rules['minReserveShifts']:
            minReserveShifts = model.NewBoolVar('minReserveShifts')
            model.Add(num_hours_reserve >= quota[librarians[n]['type']][1] - 1).OnlyEnforceIf(minReserveShifts)
            n_conditions += 1
            model.Proto().assumptions.append(minReserveShifts.Index())
        if rules['maxActiveShifts']:
            maxActiveShifts = model.NewBoolVar('maxActiveShifts')
            model.Add(num_hours_worked <= quota[librarians[n]['type']][0]).OnlyEnforceIf(maxActiveShifts)
            n_conditions += 1
            model.Proto().assumptions.append(maxActiveShifts.Index())
        if rules['maxReserveShifts']:
            maxReserveShifts = model.NewBoolVar('maxReserveShifts')
            model.Add(num_hours_reserve <= quota[librarians[n]['type']][1]).OnlyEnforceIf(maxReserveShifts)
            n_conditions += 1
            model.Proto().assumptions.append(maxReserveShifts.Index())
        if rules['holidaySpecialQuota']:
            holidaySpecialQuota = model.NewBoolVar('holidaySpecialQuota')
            model.Add(num_hours_worked >= quota[librarians[n]['type']][2] // scale).OnlyEnforceIf(holidaySpecialQuota)
            model.Proto().assumptions.append(holidaySpecialQuota.Index())
            n_conditions += 1
        
    sector_score = len(all_days)*[{}]

    model.Proto().assumptions.append(noOutOfTimeShift.Index())
        
    # TESTING: is this valid if we switch to 2h shifts, or 2.5, or 3?
    for d in all_days:
        for sector in sector_semester_quotas:
            sector_score[d][sector] = sum([shifts[(n, d, s, lo)]*desk_shifts[s][1] for n in all_librarians
                for s in all_shifts for lo in all_locations if librarians[n]['sector'] == sector])

            #model.Add(sector_score[d][sector] <= sector_semester_quotas[sector])

    # pylint: disable=g-complex-comprehension
    model.Maximize(
        sum([shift_requests[n][d][s][lo] * shifts[(n, d, s, lo)] for n in all_librarians
                    for d in all_days for s in all_shifts for lo in all_locations]))
    # Creates the solver and solve.
    solver = cp_model.CpSolver()
    #status = solver.Solve(model)
    solution_printer = cp_model.ObjectiveSolutionPrinter()
    status = solver.SolveWithSolutionCallback(model, solution_printer)

    if rules['searchForAllSolutions']:
        # Experimental: exhaustive solution search
        solver_multi = cp_model.CpSolver()
        array_solution_printer = cp_model.VVarArrayAndObjectiveSolutionPrinter([shifts[(n, d, s, lo)] for lo in all_locations
            for n in all_librarians for s in all_shifts for d in all_days])
        solver_multi.parameters.enumerate_all_solutions = True
        solutions_array = solver_multi.Solve(model, array_solution_printer)
        log_message(log_output, 'Status = %s' % solver_multi.StatusName(status))
        log_message(log_output, 'Number of solutions found: %i' % array_solution_printer.solution_count())


    log_message(log_output, '')
    log_message(log_output, 'Quality of the solution: definition of constants')
    log_message(log_output, 'cp_model.MODEL_INVALID ' + str(cp_model.MODEL_INVALID))
    log_message(log_output, 'cp_model.FEASIBLE' + str(cp_model.FEASIBLE))
    log_message(log_output, 'cp_model.INFEASIBLE'  + str(cp_model.INFEASIBLE))
    log_message(log_output, 'cp_model.OPTIMAL' + str(cp_model.OPTIMAL))
    log_message(log_output, f'-\nSolved? {str(status)} {solver.StatusName()}')
    
    if status == cp_model.INFEASIBLE:
        log_error_message(error_output, 'INFEASIBLE. Damn. Wish I knew why.')
        stat_details = f'{solver.ResponseStats()}'
        log_error_message(error_output, f"**Solver statistics:**\n{stat_details}")
        # TODO figure out the actual way to browse what makes the model INFEASIBLE.
        assump4infeasibility = eval(f'{solver.SufficientAssumptionsForInfeasibility()}')
        log_error_message(error_output, f'{len(assump4infeasibility)} assumptions are sufficient for infeasibility')
        for var_index in assump4infeasibility:
            log_error_message(error_output, f'var_index {var_index},  model.var_index_to_var_proto(var_index) {model.var_index_to_var_proto(var_index)}')
        log_error_message(error_output, '---')
        log_error_message(error_output, 'SufficientAssumptionsForInfeasibility = '
              f'{solver.SufficientAssumptionsForInfeasibility()}')
        raise(Exception("No solution could be found"))

    log_message(log_output, diagnostics)
    log_message(log_output, '')

    #report = diagnostics
    report = ''
    for d in all_days:
        line = f'Day {d}'
        frameinfo = getframeinfo(currentframe())
        log_message(log_output, f'({frameinfo.filename}:{frameinfo.lineno + 1}) {line}')
        report += '<br/>\n' + line + '<br/>\n'
        for lo in all_locations:
            for s in all_shifts:
                for n in all_librarians:
                    #print(n, d, s, lo)
                    #print(shifts[(n, d, s, lo)])
                    # FIXME don't forget the dir meeting check!!!
                    # TESTING: OK with non-1h shifts?
                    if solver.Value(shifts[(n, d, s, lo)]) == 1:
                        hh = desk_shifts[s][0] // 60
                        mm = '{:0>2}'.format(desk_shifts[s][0] % 60)
                        if shift_requests[n][d][s][lo] == 1:
                            length = desk_shifts[s][1] / 60
                            if (not d == meeting_slots[librarians[n]['sector']][0]
                                    or s < meeting_slots[librarians[n]['sector']][1]
                                    or s > meeting_slots[librarians[n]['sector']][2]) and \
                                    (not (d == meeting_slots['dir'][0] and librarians[n]['type'] == 'dir')
                                    or s < meeting_slots['dir'][1]
                                    or s > meeting_slots['dir'][2]):
                                line = f'{librarians[n]["name"]} works {length}h at {hh}:{mm} on {weekdays[d]} at {locations[lo]["name"]} (OK with work hours).'
                                log_message(log_output, line)
                                report += line + '<br>\n'
                            else:
                                line = f'{librarians[n]["name"]} works {length}h at {hh}:{mm} on {weekdays[d]} at {locations[lo]["name"]} (problem with a group meeting).'
                                log_message(log_output, f"{line} {d} {s} {meeting_slots[librarians[n]['sector']]}")
                                report += line + '<br>\n'                    
                        else:
                            line = f'{librarians[n]["name"]} works {length}h at {hh}:{mm} on {weekdays[d]} at {locations[lo]["name"]} (problem with work hours).'
                            # log_message(log_output, shift_requests[n][d])
                            log_message(log_output, line)
                            report += line + '<br/>\n'

        for sector in sector_semester_quotas:
            # TODO: is this still valid for 2h shifts, or 2.5, or 3?
            score = sum([solver.Value(shifts[(n, d, s, lo)]*desk_shifts[s][1])/60 for n in all_librarians
                        for s in all_shifts for lo in all_locations if librarians[n]['sector'] == sector])
            #score += sum([solver.Value(shifts[(n, d, all_shifts[-1], lo)]) for n in all_librarians
            #            for lo in all_locations if librarians[n]['sector'] == sector])
            
            unique_librarians = 0
            am_librarians = 0
            pm_librarians = 0
            pm = min([x for x in shift_starts if x > 12*60])
            pm_slot = shift_starts.index(pm)
            for n in all_librarians:
                worked_today = sum([solver.Value(shifts[(n, d, s, lo)]*desk_shifts[s][1]) for s in all_shifts
                    for lo in all_locations if librarians[n]['sector'] == sector])/60
                if worked_today > 0:
                    unique_librarians += 1
                worked_am = sum([solver.Value(shifts[(n, d, s, lo)]*desk_shifts[s][1]) for s in all_shifts[0:pm_slot]
                    for lo in all_locations if librarians[n]['sector'] == sector])/60
                if worked_am > 0:
                    am_librarians += 1
                worked_pm = sum([solver.Value(shifts[(n, d, s, lo)]*desk_shifts[s][1]) for s in all_shifts[pm_slot:-1]
                    for lo in all_locations if librarians[n]['sector'] == sector])/60
                if worked_pm > 0:
                    pm_librarians += 1
            line = f'Daily shifts for {sector.upper()}: {score} (using {unique_librarians} unique librarian(s), minimum {sector_semester_quotas[sector]})'
            log_message(log_output, line)
            report += line + '<br/>\n'
            line = f'Morning (8h-12h): {am_librarians} librarian(s), afternoon (after 12h-20h): {pm_librarians} librarian(s)'
            log_message(log_output, line)
            report += line + '<br/>\n'
    log_message(log_output, '')
    report += line + '<br/>\n'

    line = 'Librarians work summary'
    log_message(log_output, line)
    report += '<br/>\n' + line + '<br/>\n'
    for n in all_librarians:
        # TESTING updated to non-1h shifts
        score = sum(solver.Value(shifts[(n, d, s, lo)]*desk_shifts[s][1])/60
            for d in all_days for s in all_shifts for lo in all_locations if locations[lo]['name'].lower().find('remplacement') < 0)
        score_reserve = sum(solver.Value(shifts[(n, d, s, lo)]*desk_shifts[s][1])/60
            for d in all_days for s in all_shifts for lo in all_locations if locations[lo]['name'].lower().find('remplacement') >= 0)
        score_days = sum([1 for d in all_days if sum([solver.Value(shifts[(n, d, s, lo)]) for s in all_shifts for lo in all_locations]) > 0])
        s1 = f'{librarians[n]["name"]} is working {score}/{quota[librarians[n]["type"]][0]}'
        s2 = f' and acting as a reserve for {score_reserve}/{quota[librarians[n]["type"]][1]} hours'
        s3 = f', with {score_days} days on duty'
        line = s1 + s2 + s3
        x = sum([solver.Value(shifts[(n, d, s, lo)]) for s in all_shifts for lo in all_locations for d in all_days])
        log_message(log_output, line)
        report += line + '<br/>\n'

        log_message(log_output, librarians[n]['name'])
        for d in all_days:
            log_message(log_output, weekdays[d])
            log_message(log_output, 'availability:')
            log_message(log_output, str(shift_requests[n][d]))
            log_message(log_output, 'assigned:')
            for s in all_shifts:
                log_message(log_output, str([solver.Value(shifts[(n, d, s, lo)]) for lo in all_locations]))

    # Prepare HTML output

    main_title = "Proposed desk schedule"
    
    datatables_script = """<script type="text/javascript"
              src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.0/jquery.min.js"
              crossorigin="anonymous"></script>\n"""
    datatables_script += '<script type="text/javascript" src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>\n'
    datatables_script += '<script src="https://cdnjs.cloudflare.com/ajax/libs/mark.js/8.11.1/mark.min.js" integrity="sha512-5CYOlHXGh6QpOFA/TeTylKLWfB3ftPsde7AnmhuitiTX4K5SqCLBeKro6sPS8ilsz1Q4NRx3v8Ko2IBiszzdww==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>\n'
    datatables_script += '<script src="https://cdnjs.cloudflare.com/ajax/libs/mark.js/8.11.1/jquery.mark.es6.js" integrity="sha512-4PUcRoBmsfaiXPoigt+rm4mfuXpvvwfC7dFIhHkwVQGECJzaFDMR8HGTxNDLkwC4DlJq3/EYHL77YXFr34Jmog==" crossorigin="anonymous" referrerpolicy="no-referrer"></script>\n'
    datatables_script += '<script src=" https://cdn.jsdelivr.net/npm/datatables.mark.js@2.1.0/dist/datatables.mark.min.js "></script>\n'


    header = f"<head><title>{main_title}</title>\n{datatables_script}\n"

    header += """<style>

body {
    font-family: Arial, Helvetica, sans-serif;
}

#schedule, #guichetbiblio {  
  border collapse: collapse;
  width: 100%;
}

#schedule td, #schedule th {
  border: 1px solid #ddd;
  padding: 8px;
}

#guichetbiblio td, #guichetbiblio th {
  border: 1px solid #ddd;
  padding: 8px;
}

#schedule tr:nth-child(even){background-color: #f2f2f2;}
#guichetbiblio tr:nth-child(even){background-color: #f2f2f2;}

#schedule tr:hover {background-color: #ddd;}
#guichetbiblio tr:hover {background-color: #ddd;}

#schedule th {
  padding-top: 12px;
  padding-bottom: 12px;
  text-align: left;
  background-color: #04AA6D;
  color: white;
}

#guichetbiblio th {
  padding-top: 12px;
  padding-bottom: 12px;
  text-align: left;
  background-color: #0000FF;
  color: white;
}
</style></head>"""

    title = f"<h1>{main_title}</h1>"

    max_score = 0
    for d in all_days:
        for s in all_shifts:
            for lo in all_locations:
                if s < locations[lo]['times'][d]['start'] or s > locations[lo]['times'][d]['end']:
                    pass
                elif s == all_shifts[-1] and (d == all_days[-1]):
                    pass
                else:
                    max_score += 1 
    score = f"Solution score = {solver.ObjectiveValue()} (max possible result {max_score})\n"
    score += f"<br/>{n_conditions} conditions evaluated\n"
    score += f"<br/>Run on {datetime.now().isoformat()}\n"
    stat_details = f'{solver.ResponseStats()}'

    guichetbiblio_table = '<div><table id="guichetbiblio" class="table">\n'
    guichetbiblio_table += '<thead>'
    guichetbiblio_table += "<tr>\n"
    guichetbiblio_table += '<th scope="col">Poste</th>'
    for s in all_shifts:
        # TODO: definitely not valid if we switch to 2h shifts, or 2.5, or 3?
        hh1 = '{:0>2}'.format(desk_shifts[s][0] // 60)
        mm1 = '{:0>2}'.format(desk_shifts[s][0] % 60)
        hh2 = '{:0>2}'.format((desk_shifts[s][0] + desk_shifts[s][1]) // 60)
        mm2 = '{:0>2}'.format((desk_shifts[s][0] + desk_shifts[s][1]) % 60)
        guichetbiblio_table += f'<th scope="col">{hh1}:{mm1}-{hh2}:{mm2}</th>'
    guichetbiblio_table += "\n</tr>\n</thead>\n<tbody>"
    for d in all_days:
        for lo in all_locations:
            guichetbiblio_table += "<tr>\n"
            guichetbiblio_table += f"<td>{weekdays[d]} {locations[lo]['name']}</td>"
            for s in all_shifts:
                cell = "<td>N/A</td>"
                for n in all_librarians:
                    if solver.Value(shifts[(n, d, s, lo)]) == 1:
                        cell = f"<td>{librarians[n]['name']}</td>"
                guichetbiblio_table += cell
            guichetbiblio_table += "</tr>\n"
        # Empty row for better readability
        guichetbiblio_table += "<tr>"
        guichetbiblio_table += '<td></td>'
        for s in all_shifts:
            guichetbiblio_table += '<td></td>'
        guichetbiblio_table += "</tr>\n"

    guichetbiblio_table += "</tbody></table></div>"

    table = '<div><table id="schedule" class="table">\n'
    table += '<thead>'
    table += "<tr>\n"
    table += '<th scope="col">Time</th>'
    for d in all_days:
        table += f'<th scope="col">{weekdays[d]}</th>'
    
    table += "\n</tr>\n</thead>\n<tbody>"

    for s in all_shifts:
        for lo in all_locations:
            table += "<tr>\n"
            hh1 = '{:0>2}'.format(desk_shifts[s][0] // 60)
            mm1 = '{:0>2}'.format(desk_shifts[s][0] % 60)
            hh2 = '{:0>2}'.format((desk_shifts[s][0] + desk_shifts[s][1]) // 60)
            mm2 = '{:0>2}'.format((desk_shifts[s][0] + desk_shifts[s][1]) % 60)
            table += f"<td>{hh1}:{mm1}-{hh2}:{mm2} {locations[lo]['name']}</td>"
            for d in all_days:
                cell = "<td>N/A</td>"
                for n in all_librarians:
                    if solver.Value(shifts[(n, d, s, lo)]) == 1:
                        cell = f"<td>{librarians[n]['name']}</td>"
                table += cell

            table += "\n</tr>\n"

    table +=  "</tbody></table></div>"

    datatables_init = """
    <script>
    $(document).ready(function() {
        $('#schedule').DataTable({
            "paging": false,
            "mark": true
        });
        $('#guichetbiblio').DataTable({
            "paging": false,
            "mark": true,
            "ordering": false
        });
    });
  </script>
    """
    body = f"<body>\n{title}\n{datatables_init}\n"
    body += f"<h2>Diagnostics:</h2>\n<pre><code>{diagnostics}</code></pre>"
    body += "<h2>Technical statistics:</h2>"
    body += f"<div>{score}</div>\n<pre><code>{stat_details}</code></pre>"
    body += "\n<h2>Summary table (for guichetbiblio.epfl.ch)</h2>"
    body += f"\n{guichetbiblio_table}"
    body += "\n<h2>Summary table (for other use cases)</h2>"
    body += f"\n{table}"
    body += f'\n<div>{report}</div></body>'

    html = f"<!DOCTYPE html>\n<html>\n{header}\n{body}</html>"

    outfile = open(parameter_file.replace('.xlsx', '') + '.html', 'w')
    outfile.write(html)
    outfile.close()

    # Statistics

    log_message(log_output, '')
    log_message(log_output, '**Statistics:**')
    log_message(log_output, f' - {score}')
    log_message(log_output, '')
    log_message(log_output, f"**Solver statistics:**\n{stat_details}")

    """
    if rules['preferedRunLength']:
        for n in all_librarians:
            if librarians[n]['prefered_length'] > 1:
                for d in all_days:
                    for s in all_shifts[0:-1]:
                        for lo in all_locations:
                            log_message(log_output, f'shifts:  {(n, d, s, lo)} {solver.Value(shifts[(n, d, s, lo)])}')
                        log_message(log_output, f'delta1: {(n, d, s, lo)} {solver.Value(delta_vars1[(n, d, s)])}')
                        log_message(log_output, f'delta2: {(n, d, s, lo)} {solver.Value(delta_vars2[(n, d, s)])}')
    """


if __name__ == '__main__':
    script_description = 'Generate a desk schedule from a file or from the variables in a Python script'
    parser = argparse.ArgumentParser(description=script_description)
    parser.add_argument('--no-file', action='store_true', help='do not read from Excel sheet, use work_schedule.py')
    parser.add_argument('--file', help='read from Excel sheet')

    args = parser.parse_args()
    log_message(log_output, str(args))

    if args.no_file:
        filename = ''
    elif args.file is not None:
        filename = args.file
    else:
        filename = 'Horaires-guichets.xlsx'

    log_output = filename.replace('.xlsx', '') + '_log.txt'
    error_output = filename.replace('.xlsx', '') + '_errors.txt'
    main(filename, log_output, error_output)

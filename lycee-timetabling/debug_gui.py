from __future__ import annotations
import csv
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from collections import Counter, defaultdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

DAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
LESSON_PATTERN = re.compile(r'^\(([^,]+),([^,]+),([^,]+)\)$')
BASE = Path(__file__).resolve().parent


def csv_rows(path):
    if not path or not Path(path).is_file():
        return []
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def lesson_records(path):
    records = []
    for row in csv_rows(path):
        try:
            slot = int(row['slot_index'])
        except (KeyError, ValueError, TypeError):
            continue
        for field in (row.get('assignments') or '').split(';'):
            m = LESSON_PATTERN.fullmatch(field.strip())
            if m:
                teacher, course, room = (part.strip() for part in m.groups())
                records.append({'slot_index': slot, 'timeslot': row.get('timeslot', ''), 'course': course, 'professor': teacher, 'room': room})
    return records


def dependency_summary(input_rows, student_rows):
    rules = [r for r in input_rows if (r.get('kind') or '').lower() == 'dependency']
    students_by_subject = defaultdict(set)
    students_by_family = defaultdict(set)
    students_by_course = defaultdict(set)
    course_family = {r.get('id', ''): r.get('family', '') for r in input_rows if r.get('kind') == 'course'}
    for r in student_rows:
        student = r.get('student', '')
        family = course_family.get(r.get('course', ''), '')
        if student and family:
            students_by_family[family].add(student)
        students_by_course[r.get('course', '')].add(student)
        students_by_subject[r.get('subject', '')].add(student)
    summary = []
    for dep in rules:
        source_family = dep.get('from_family', '')
        source_course = dep.get('from_course', '')
        target = dep.get('to_family', '')
        active = students_by_family[source_family] if source_family else students_by_course[source_course]
        covered = students_by_family[target]
        summary.append({
            'source': source_family or f'course:{source_course}',
            'target': target,
            'kind': 'Required' if (dep.get('required','true') or 'true').lower() in ('true','1','yes','y') else 'Optional',
            'activated': len(active),
            'covered': len(active & covered),
            'unmet': len(active - covered),
            'weight': dep.get('weight','') or '1'
        })
    return summary


class Debugger(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Lycée Timetable — Debugger')
        self.geometry('1170x795')
        self.minsize(850, 590)
        self.jobs = queue.Queue()
        self.busy = False
        self.input_path = tk.StringVar()
        self.master_path = tk.StringVar()
        self.student_path = tk.StringVar()
        self.limit = tk.StringVar(value='15')
        self.local = tk.StringVar(value='6')
        self.seed = tk.StringVar(value='2026')
        self.slots = tk.StringVar(value='40')
        self.daylength = tk.StringVar(value='8')
        self.filter_kind = tk.StringVar(value='All lessons')
        self.filter_value = tk.StringVar()
        self.overview = tk.StringVar(value='Choose an input CSV, or open the bundled linked-course example.')
        self.status = tk.StringVar(value='Ready')
        self.input_rows = []
        self.lectures = []
        self.student_rows = []
        self._build()
        self.after(120, self._poll)

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        files = ttk.LabelFrame(self, text='Files')
        files.grid(row=0, column=0, padx=10, pady=(9, 4), sticky='ew')
        files.columnconfigure(1, weight=1)
        for i, (label, value, method) in enumerate([
            ('Input CSV', self.input_path, self._choose_input),
            ('School timetable', self.master_path, self._choose_master),
            ('Student timetables', self.student_path, self._choose_student),
        ]):
            ttk.Label(files, text=label, width=18).grid(row=i, column=0, padx=6, pady=3, sticky='w')
            ttk.Entry(files, textvariable=value).grid(row=i, column=1, padx=6, pady=3, sticky='ew')
            ttk.Button(files, text='Browse', command=method, width=10).grid(row=i, column=2, padx=6, pady=3)
        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, padx=10, pady=5, sticky='ew')
        for label, variable, width in [
            ('Time (s)', self.limit, 5), ('Local (s)', self.local, 5), ('Seed', self.seed, 7),
            ('Slots', self.slots, 4), ('Per day', self.daylength, 4)
        ]:
            ttk.Label(controls, text=label).pack(side='left', padx=(2, 3))
            ttk.Entry(controls, textvariable=variable, width=width).pack(side='left', padx=(0, 11))
        self.buttons = []
        for text, command in [('Open example', self._example), ('Run solver', self._solve), ('Validate', self._validate), ('Refresh views', self._refresh)]:
            b = ttk.Button(controls, text=text, command=command)
            b.pack(side='left', padx=4)
            self.buttons.append(b)
        notebook = ttk.Notebook(self)
        notebook.grid(row=2, column=0, padx=10, pady=4, sticky='nsew')
        self.week_tab = ttk.Frame(notebook)
        self.lessons_tab = ttk.Frame(notebook)
        self.link_tab = ttk.Frame(notebook)
        self.log_tab = ttk.Frame(notebook)
        notebook.add(self.week_tab, text='Week grid')
        notebook.add(self.lessons_tab, text='Lessons')
        notebook.add(self.link_tab, text='Linked subjects')
        notebook.add(self.log_tab, text='Validation / Console')
        self._make_week_tab()
        self.lecture_table = self._make_table(self.lessons_tab, ('slot', 'time', 'course', 'subject', 'teacher', 'room', 'student'), (60, 190, 220, 130, 160, 100, 160))
        self.link_table = self._make_table(self.link_tab, ('source', 'target', 'kind', 'activated', 'covered', 'unmet', 'weight'), (240, 180, 100, 110, 110, 100, 80))
        self.link_caption = ttk.Label(self.link_tab, text='Required: taking the source obliges the target. Optional: target may be added, never required.', wraplength=900)
        self.link_caption.pack(side='bottom', anchor='w', padx=8, pady=4)
        self.console = tk.Text(self.log_tab, wrap='word', font=('Consolas', 10), state='disabled')
        console_scroll = ttk.Scrollbar(self.log_tab, orient='vertical', command=self.console.yview)
        self.console.configure(yscrollcommand=console_scroll.set)
        self.console.pack(side='left', expand=True, fill='both')
        console_scroll.pack(side='right', fill='y')
        footer = ttk.Frame(self)
        footer.grid(row=3, column=0, padx=10, pady=(3, 10), sticky='ew')
        ttk.Label(footer, textvariable=self.overview).pack(side='left', fill='x', expand=True)
        ttk.Label(footer, textvariable=self.status).pack(side='right')

    def _make_table(self, parent, columns, widths):
        wrapper = ttk.Frame(parent)
        wrapper.pack(fill='both', expand=True)
        wrapper.rowconfigure(0, weight=1)
        wrapper.columnconfigure(0, weight=1)
        t = ttk.Treeview(wrapper, columns=columns, show='headings', selectmode='browse')
        for col, width in zip(columns, widths):
            t.heading(col, text=col.replace('_',' ').title())
            t.column(col, width=width, anchor='w', stretch=True)
        t.grid(row=0, column=0, sticky='nsew')
        sy = ttk.Scrollbar(wrapper, orient='vertical', command=t.yview)
        sx = ttk.Scrollbar(wrapper, orient='horizontal', command=t.xview)
        t.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.grid(row=0,column=1,sticky='ns')
        sx.grid(row=1,column=0,sticky='ew')
        t.bind('<Double-1>', self._show_row)
        return t

    def _make_week_tab(self):
        selectors = ttk.Frame(self.week_tab)
        selectors.pack(fill='x', padx=7, pady=7)
        ttk.Label(selectors, text='View').pack(side='left', padx=4)
        options = ('All lessons','Student','Teacher','Room','Class aggregate','Class common','Teaching group')
        view = ttk.Combobox(selectors, textvariable=self.filter_kind, values=options, state='readonly', width=15)
        view.pack(side='left', padx=4)
        view.bind('<<ComboboxSelected>>', lambda _e: self._on_filter_type())
        ttk.Label(selectors, text='ID').pack(side='left', padx=4)
        self.filter_box = ttk.Combobox(selectors, textvariable=self.filter_value, width=34)
        self.filter_box.pack(side='left', padx=4)
        self.filter_box.bind('<<ComboboxSelected>>', lambda _e: self._update_tables())
        self.filter_box.bind('<Return>', lambda _e: self._update_tables())
        ttk.Button(selectors, text='Apply', command=self._update_tables).pack(side='left', padx=6)
        self.week_table = self._make_table(self.week_tab, ('period', *DAYS[:5]), (100, 205, 205, 205, 205, 205))

    def _show_row(self, event):
        table = event.widget
        target = table.focus()
        if target:
            vals = table.item(target).get('values')
            messagebox.showinfo('Record details', '\n'.join(f'{c}: {v}' for c,v in zip(table['columns'], vals)))

    def _choose_input(self):
        p = filedialog.askopenfilename(filetypes=[('CSV files','*.csv'),('All files','*.*')])
        if p:
            self.input_path.set(p)
            base = Path(p).parent
            self.master_path.set(str(base / 'timetable.csv'))
            self.student_path.set(str(base / 'students.csv'))
            self._refresh()

    def _choose_master(self):
        p = filedialog.askopenfilename(filetypes=[('CSV files','*.csv')])
        if p:
            self.master_path.set(p)
            self._refresh()

    def _choose_student(self):
        p = filedialog.askopenfilename(filetypes=[('CSV files','*.csv')])
        if p:
            self.student_path.set(p)
            self._refresh()

    def _example(self):
        p = BASE / 'examples' / 'linked_courses.csv'
        self.input_path.set(str(p))
        self.slots.set('8')
        self.daylength.set('4')
        self.master_path.set(str(BASE / 'examples' / 'demo_timetable.csv'))
        self.student_path.set(str(BASE / 'examples' / 'demo_students.csv'))
        self._refresh()

    def _refresh(self):
        try:
            self.input_rows = csv_rows(self.input_path.get())
            self.lectures = lesson_records(self.master_path.get())
            self.student_rows = csv_rows(self.student_path.get())
            self._on_filter_type()
            self._fill_links()
            counts = Counter(r.get('kind','') for r in self.input_rows)
            self.overview.set(f"Input: {counts['course']} sessions, {counts['student']} pupils, {counts['group']} groups, {counts['dependency']} dependencies  |  Output: {len(self.lectures)} assigned lessons, {len(self.student_rows)} pupil-lesson rows")
        except Exception as exc:
            self._append(f'Error refreshing outputs: {exc}')
            messagebox.showerror('CSV error',str(exc))

    def _on_filter_type(self):
        kind = self.filter_kind.get()
        if kind == 'Student':
            values = sorted({r.get('student','') for r in self.student_rows if r.get('student')})
        elif kind == 'Teacher':
            values = sorted({r.get('professor','') for r in self.lectures if r.get('professor')})
        elif kind == 'Room':
            values = sorted({r.get('room','') for r in self.lectures if r.get('room')})
        elif kind in {'Class','Class aggregate','Class common'}:
            values = sorted({r.get('home_class','') for r in self.student_rows if r.get('home_class')})
        elif kind == 'Teaching group':
            values = sorted({r.get('group_id','') for r in self.input_rows if r.get('kind') == 'group'} | {r.get('section','') for r in self.student_rows if r.get('section')})
            values = [v for v in values if v]
        else:
            values = []
        self.filter_box.configure(values=values)
        if self.filter_value.get() not in values:
            self.filter_value.set(values[0] if values else '')
        self._update_tables()

    def _selected(self):
        kind = self.filter_kind.get()
        val = self.filter_value.get().strip()
        if kind == 'Student':
            return [r for r in self.student_rows if r.get('student') == val]
        if kind in {'Class','Class aggregate','Class common'}:
            rows = [r for r in self.student_rows if r.get('home_class') == val]
            if kind == 'Class common':
                pupils = {r.get('student') for r in rows}
                rosters = defaultdict(set)
                for r in rows:
                    rosters[r.get('course')].add(r.get('student'))
                common = {c for c, who in rosters.items() if len(who) == len(pupils)}
                rows = [r for r in rows if r.get('course') in common]
            return rows
        if kind == 'Teaching group':
            course_group = {r.get('id'): r.get('group_id') for r in self.input_rows if r.get('kind') == 'course'}
            return [r for r in self.student_rows if r.get('section') == val or course_group.get(r.get('course')) == val]
        if kind in ('Teacher','Room'):
            key = 'professor' if kind == 'Teacher' else 'room'
            return [r for r in self.lectures if r.get(key)==val]
        return self.lectures

    def _update_tables(self):
        selected = self._selected()
        self.week_table.delete(*self.week_table.get_children())
        self.lecture_table.delete(*self.lecture_table.get_children())
        try:
            period_count = max(1,int(self.daylength.get()))
            slots = max(1,int(self.slots.get()))
        except ValueError:
            period_count,slots=8,40
        n_days = min(5,(slots+period_count-1)//period_count)
        by_slot = defaultdict(list)
        aggregate = self.filter_kind.get() in {'Class','Class aggregate','Class common','Teaching group'}
        counts = Counter((r.get('slot_index'), r.get('course')) for r in selected)
        total_pupils = len({r.get('student') for r in selected}) if aggregate else 0
        emitted = set()
        for r in selected:
            if aggregate:
                identity = (r.get('slot_index'), r.get('course'))
                if identity in emitted:
                    continue
                emitted.add(identity)
            try:
                t = int(r['slot_index'])
            except (KeyError, ValueError,TypeError):
                continue
            course = r.get('course','')
            teacher = r.get('professor','')
            section = r.get('section','')
            display = course if self.filter_kind.get() != 'All lessons' else f'{course} [{r.get("room", "")}]'
            if aggregate:
                display += f' ({counts[(r.get("slot_index"),course)]}/{total_pupils})'
            if section and self.filter_kind=='Student':
                display += f' / {section}'
            by_slot[t].append(display)
            self.lecture_table.insert('', 'end', values=(t,r.get('timeslot',''),course,r.get('subject',''),teacher,r.get('room',''),r.get('student','')))
        for h in range(period_count):
            values = [f'{h+1:02d}']
            for d in range(5):
                t=d*period_count+h
                if d>=n_days or t>=slots:
                    values.append('')
                    continue
                entries=by_slot[t]
                if len(entries)>3:
                    values.append(' | '.join(entries[:3])+f'  (+{len(entries)-3})')
                else:
                    values.append(' | '.join(entries))
            self.week_table.insert('', 'end', values=values)

    def _fill_links(self):
        self.link_table.delete(*self.link_table.get_children())
        for r in dependency_summary(self.input_rows, self.student_rows):
            self.link_table.insert('', 'end', values=tuple(r[k] for k in ('source','target','kind','activated','covered','unmet','weight')))

    def _append(self, line):
        self.console.configure(state='normal')
        self.console.insert('end',str(line)+'\n')
        self.console.see('end')
        self.console.configure(state='disabled')

    def _run(self, command, name):
        if self.busy:
            return
        self.busy = True
        self.status.set(f'Running {name}…')
        for b in self.buttons:
            b.state(['disabled'])
        self._append(f'$ {subprocess.list2cmdline(command)}')
        def worker():
            try:
                budget = (float(self.limit.get()) + 60) if name == 'Solver' else 180
                result=subprocess.run(command,capture_output=True,text=True,timeout=max(180, budget))
                self.jobs.put((name,result.returncode,result.stdout,result.stderr))
            except Exception as exc:
                self.jobs.put((name,-1,'',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def _poll(self):
        try:
            while True:
                name,code,out,err=self.jobs.get_nowait()
                if out.strip():
                    self._append(out.strip())
                if err.strip():
                    self._append(err.strip())
                self._append(f'{name} returned exit code {code}')
                self.status.set(f'{name}: {"OK" if code == 0 else "FAILED"}')
                self.busy=False
                for b in self.buttons:
                    b.state(['!disabled'])
                if name != 'Solver' or code == 0:
                    self._refresh()
                else:
                    self._append('No new timetable was produced. Existing output files, if any, are from an earlier run.')
        except queue.Empty:
            pass
        self.after(120,self._poll)

    def _solve(self):
        if not self.input_path.get() or not Path(self.input_path.get()).is_file():
            messagebox.showerror('Missing input','Select an existing input CSV.')
            return
        try:
            limit=float(self.limit.get());local=float(self.local.get())
            slots=int(self.slots.get());day=int(self.daylength.get())
            seed=int(self.seed.get())
            if min(limit,slots,day)<=0 or local<0:
                raise ValueError('positive values required')
        except ValueError as exc:
            messagebox.showerror('Invalid parameter',str(exc))
            return
        master=self.master_path.get() or str(Path(self.input_path.get()).with_name('timetable.csv'))
        student=self.student_path.get() or str(Path(self.input_path.get()).with_name('students.csv'))
        Path(master).parent.mkdir(parents=True,exist_ok=True)
        Path(student).parent.mkdir(parents=True,exist_ok=True)
        self.master_path.set(master);self.student_path.set(student)
        diagnostic_path = str(Path(master).with_suffix('.diagnostics.json'))
        cmd=[sys.executable,str(BASE/'timetable_csv.py'),self.input_path.get(),master,'--students-output',student,'--time-limit',str(limit),'--local-seconds',str(local),'--slots',str(slots),'--slots-per-day',str(day),'--seed',str(seed),'--diagnostics',diagnostic_path]
        self._run(cmd,'Solver')

    def _validate(self):
        for p in (self.input_path.get(),self.master_path.get(),self.student_path.get()):
            if not Path(p).is_file():
                messagebox.showerror('Missing file',f'File not found:\n{p}')
                return
        cmd=[sys.executable,str(BASE/'validate_timetable_csv.py'),self.input_path.get(),self.master_path.get(),'--students-output',self.student_path.get(),'--slots',self.slots.get(),'--slots-per-day',self.daylength.get()]
        self._run(cmd,'Validator')


def main():
    app=Debugger()
    app.mainloop()

if __name__=='__main__':
    main()

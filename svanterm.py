# Todos:
# - Integrate tag dragging between windows with normal dragging in tabcontrol
# - Broadcast to terminals
# - Ctrl + Shift + number to select terminal (with hints)
# - Make splitter bigger horizontally and vertically
# - Split into files
# - Comment the code :)
# - Detect missing cygwin on start (seems to die silently now)
# - Add recommended bashrc / some tips and tricks setting up / using cygwin
# - Too many focus events are sent when splitting to new window and then selecting a terminal in the old window

from ctypes import *
import pywintypes
import Queue
import subprocess
import sys
import threading
import time
import traceback
import win32api
import win32con
import win32event
import win32gui
import win32process
import winerror
import wx
import wx.lib.agw.aui as aui
import wx.lib.agw.ultimatelistctrl as ultimatelistctrl

PROGRAM_TITLE = "SvanTerm 0.2"
user32 = windll.user32

DOCK_TOP = 1
DOCK_LEFT = 2
DOCK_RIGHT = 3
DOCK_BOTTOM = 4
DOCK_NEW_WINDOW = 5


def get_hwnd_for_pid(pid):
    def callback(hwnd, hwnds):
        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
        if found_pid == pid:
            hwnds.append(hwnd)
        return True

    while 1:
        hwnds = []
        win32gui.EnumWindows(callback, hwnds)
        for hwnd in hwnds:
            if win32gui.GetParent(hwnd) == 0:
                return hwnd

        time.sleep(0.01)


class TerminalHeader(wx.StaticText):
    def __init__(self, parent, label=''):
        super(TerminalHeader, self).__init__(parent)

        self.label = label
        self.enabled = True
        self.Bind(wx.EVT_PAINT, self.on_paint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, lambda event: None)
        self.Bind(wx.EVT_SIZE, self.on_size)

    def on_paint(self, event):
        dc = wx.AutoBufferedPaintDCFactory(self)

        if self.enabled:
            dc.GradientFillLinear(
                self.GetClientRect(), wx.RED,
                wx.Colour(100, 0, 0), wx.SOUTH)
            dc.SetTextForeground(wx.WHITE)
        else:
            dc.GradientFillLinear(
                self.GetClientRect(), wx.Colour(220, 220, 220),
                wx.Colour(150, 150, 150), wx.SOUTH)
            dc.SetTextForeground(self.GetForegroundColour())

        dc.SetFont(wx.Font(12, wx.MODERN, wx.NORMAL, wx.NORMAL))
        tw, th = dc.GetTextExtent(self.label)
        dc.DrawText(self.label, (self.GetSize()[0] - tw) / 2,
                    (self.GetSize()[1] - th) / 2)

    def on_size(self, event):
        self.Refresh()
        event.Skip()

    def SetLabel(self, label):
        self.label = label
        self.Refresh()


class Terminal(wx.Window):

    def __init__(self, parent, app):
        super(Terminal, self).__init__(parent)
        self.app = app
        self.SetBackgroundColour(wx.BLACK)

        self.terminal_hwnd = get_hwnd_for_pid(self.app.cached_terminal.pid)
        self.app.hwnd_to_terminal[self.terminal_hwnd] = self

        self.title = win32gui.GetWindowText(self.terminal_hwnd)
        self.text = TerminalHeader(self, self.title)

        self.Bind(wx.EVT_SIZE, self.OnSize)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.OnDestroy)
        self.text.Bind(wx.EVT_MIDDLE_DOWN, self.Destroy)

        win32gui.SetWindowLong(self.terminal_hwnd, win32con.GWL_STYLE,
                               win32con.WS_CHILD | win32con.WS_VSCROLL)
        win32gui.SetParent(self.terminal_hwnd, self.GetHandle())
        self.GetParent().OnSize()
        win32gui.ShowWindow(self.terminal_hwnd, win32con.SW_SHOW)
        self.app.spawn_terminal()

    def ShowDockHint(self, mouse_pos):
        size = self.GetClientSize()
        terminal_pos = self.GetScreenPosition()
        center = (size[0] / 2, size[1] / 2)
        from_center = (mouse_pos[0] - center[0], mouse_pos[1] - center[1])

        if abs(from_center[0]) > abs(from_center[1]):
            if from_center[0] <= 0:
                self.app.dock_pos = DOCK_LEFT
            else:
                self.app.dock_pos = DOCK_RIGHT
        else:
            if from_center[1] <= 0:
                self.app.dock_pos = DOCK_TOP
            else:
                self.app.dock_pos = DOCK_BOTTOM

        if self.app.dock_pos == DOCK_LEFT:
            self.app.dock_hint.SetRect(
                wx.Rect(terminal_pos[0], terminal_pos[1], center[0], size[1]))
        elif self.app.dock_pos == DOCK_RIGHT:
            self.app.dock_hint.SetRect(
                wx.Rect(terminal_pos[0] + center[0], terminal_pos[1],
                        center[0], size[1]))
        elif self.app.dock_pos == DOCK_TOP:
            self.app.dock_hint.SetRect(
                wx.Rect(terminal_pos[0], terminal_pos[1], size[0], center[1]))
        elif self.app.dock_pos == DOCK_BOTTOM:
            self.app.dock_hint.SetRect(
                wx.Rect(terminal_pos[0], terminal_pos[1] + center[1],
                        size[0], center[1]))

        self.app.dock_to = self

    def OnSize(self, event=None):
        self.app.move_window_thread.request_queue.put(self)
        self.text.SetSize((self.GetSize()[0], 20))

    def Destroy(self, event=None):
        terminal_list = self.app.build_terminal_list(self.GetParentTab())
        terminal_index = terminal_list.index(self)

        if len(terminal_list) > 1:
            if self.GetGrandParent().panel1 == self.GetParent():
                self.app.focus_terminal(
                    terminal_list[terminal_list.index(self) + 1])
            else:
                self.app.focus_terminal(
                    terminal_list[terminal_list.index(self) - 1])

        self.GetParent().Hide()
        wx.CallAfter(self.GetParent().Destroy)
        super(Terminal, self).Destroy()

    def GetParentTab(self):
        child = self
        while not isinstance(child.GetParent(), TabControl):
            child = child.GetParent()

        return child

    def OnDestroy(self, event):
        try:
            win32api.PostMessage(self.terminal_hwnd, win32con.WM_QUIT)
        except pywintypes.error:
            pass

    def __del__(self):
        del self.app.hwnd_to_terminal[self.terminal_hwnd]
        super(Terminal, self).__del__()


class Splitter(wx.SplitterWindow):

    def __init__(self, parent, app):
        super(Splitter, self).__init__(
            parent, style=wx.SP_LIVE_UPDATE + wx.SP_3D)
        self.Hide()
        self.app = app
        self.SetBackgroundColour(wx.BLACK)
        self.SetSashGravity(0.5)
        self.SetSize(parent.GetClientSize())
        self.panel1 = Container(self, self.app)
        self.panel2 = Container(self, self.app)
        self.panel1.Bind(wx.EVT_WINDOW_DESTROY, self.OnChildDestoyed)
        self.panel2.Bind(wx.EVT_WINDOW_DESTROY, self.OnChildDestoyed)
        # To prevent the splitter from unsplit on doubleclick
        self.SetMinimumPaneSize(1)

    def OnChildDestoyed(self, event):
        if self.IsBeingDeleted():
            return

        if event.GetWindow() == self.panel1:
            remaining_panel = self.panel2
        elif event.GetWindow() == self.panel2:
            remaining_panel = self.panel1
        else:
            return

        for child in remaining_panel.GetChildren():
            child.Reparent(self.GetParent())

        child.SetSize(self.GetParent().GetClientSize())

        # Schedule a destroy, can't run this directly from this event as this
        # will crash python
        self.Hide()
        wx.CallAfter(self.Destroy)


class Container(wx.Window):

    def __init__(self, parent, app, size=(100, 100)):
        super(Container, self).__init__(parent, size=size, pos=(10000, 10000))
        self.active_terminal = None
        self.app = app
        self.custom_name = ""
        self.SetBackgroundColour(wx.BLACK)
        self.Bind(wx.EVT_SIZE, self.OnSize)

    def OnSize(self, event=None, force=False):
        if force or self.IsShown():
            for child in self.GetChildren():
                child.SetSize(self.GetClientSize())

    def Destroy(self):
        if isinstance(self.GetParent(), TabControl):
            self.GetParent().RemoveTab(self)
        super(Container, self).Destroy()


class TabControl(aui.AuiNotebook):

    def __init__(self, parent, app):
        super(TabControl, self).__init__(parent, agwStyle=aui.AUI_NB_TAB_MOVE
                                         | aui.AUI_NB_MIDDLE_CLICK_CLOSE)
        self.app = app
        self.SetBackgroundColour(wx.BLACK)
        self.Bind(aui.EVT_AUINOTEBOOK_PAGE_CHANGED, self.OnPageChanged)
        self.Bind(aui.EVT_AUINOTEBOOK_END_LABEL_EDIT, self.OnLabelEdited)

    def AddTab(self, new_tab, title):
        new_tab.SetSize(self.GetClientSize())
        self.AddPage(new_tab, title, select=True)
        self.SetRenamable(self.GetSelection(), True)
        return new_tab

    def RemoveTab(self, tab):
        if self.GetPageCount() == 1:
            wx.CallAfter(self.GetParent().Close)
            return

        page_index = self.GetPageIndex(tab)
        self.RemovePage(page_index)

    def DeletePage(self, page_idx):
        if self.GetPageCount() == 1:
            wx.CallAfter(self.GetParent().Close)
            return

        self.GetPage(page_idx).Destroy()

    def ActivateTabAtPoint(self, x, y):
        pos = self.ScreenToClient((x, y))
        tab = self.GetTabCtrlFromPoint((1, 1)).TabHitTest(pos[0], pos[1])
        if tab:
            self.SetSelectionToWindow(tab)

    def OnPageChanged(self, event):
        self.GetCurrentPage().OnSize(force=True)

        if (not self.app.dock_from and
           self.GetCurrentPage().active_terminal and
           not self.app.find_dialog.IsShown()):
            self.app.focus_terminal(self.GetCurrentPage().active_terminal)

    def OnLabelEdited(self, event):
        if self.GetPageText(event.GetSelection()) == event.GetLabel():
            return

        self.GetPage(event.GetSelection()).custom_name = event.GetLabel()
        wx.CallAfter(self.app.update_title,
                     self.GetCurrentPage().active_terminal.terminal_hwnd)
        wx.CallAfter(self.app.focus_terminal,
                     self.GetCurrentPage().active_terminal)

    def OnTabBeginDrag(self, event):
        self.app.InitiateDragDrop(self.GetCurrentPage())

    def OnTabEndDrag(self, event):
        self.app.dock_from = None
        self.app.dock_hint.Hide()


class TerminalWindow(wx.Frame):

    def __init__(self, app):
        super(TerminalWindow, self).__init__(
            None, -1, PROGRAM_TITLE, size=(800, 600))
        self.SetBackgroundColour(wx.BLACK)
        self.app = app
        self.tabs = TabControl(self, self.app)
        self.Show(True)

        self.app.hwnd_to_terminal_window[self.GetHandle()] = self
        self.app.SetTopWindow(self)
        self.Bind(wx.EVT_CLOSE, self.OnClose)

    def OnClose(self, event):
        del self.app.hwnd_to_terminal_window[self.GetHandle()]

        if len(self.app.hwnd_to_terminal_window) == 0:
            win32api.PostMessage(
                get_hwnd_for_pid(self.app.cached_terminal.pid),
                win32con.WM_QUIT)
            user32.UnhookWindowsHookEx(self.app.keyboard_hook)
            user32.UnhookWindowsHookEx(self.app.mouse_hook)
            user32.UnhookWinEvent(self.app.terminal_event_hook)
            self.app.dock_hint.Destroy()
            self.app.find_dialog.Destroy()

        event.Skip()


class FindDialog(wx.Frame):

    def __init__(self, app):
        super(FindDialog, self).__init__(
            None, -1, PROGRAM_TITLE, size=(400, 200), style=wx.STAY_ON_TOP)
        self.app = app
        self.SetTransparent(200)
        self.text = wx.TextCtrl(
            self, size=(398, 20), style=wx.TE_PROCESS_ENTER)
        self.text.SetBackgroundColour(wx.Colour(50, 50, 50))
        self.text.SetForegroundColour(wx.WHITE)
        self.list = ultimatelistctrl.UltimateListCtrl(
            self, wx.ID_ANY,
            agwStyle=wx.LC_REPORT | wx.LC_NO_HEADER | wx.LC_SINGLE_SEL,
            pos=(0, 20), size=(600, 180))
        self.list.InsertColumn(0, "")
        self.list.InsertColumn(1, "")
        self.list.SetColumnWidth(0, 250)
        self.list.SetColumnWidth(1, 144)

        self.list.SetBackgroundColour(wx.Colour(0, 0, 0))
        self.list.SetTextColour(wx.WHITE)
        self.list.EnableSelectionGradient(True)

        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnItemActivated)
        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnSelect)
        self.list.Bind(wx.EVT_LEFT_DOWN, self.OnLeftDown)
        self.text.Bind(wx.EVT_TEXT, self.Filter)
        self.text.Bind(wx.EVT_TEXT_ENTER, self.OnItemActivated)
        self.text.Bind(wx.EVT_KEY_DOWN, self.OnKeyDown)

    def Filter(self, event=None):
        text = self.text.GetValue().upper()
        self.list.DeleteAllItems()

        for terminal in self.app.hwnd_to_terminal.values():
            tab_title = terminal.GetParentTab().custom_name
            if (terminal.title.upper().find(text) != -1 or
                    tab_title.upper().find(text) != -1):
                item = self.list.InsertStringItem(sys.maxint, terminal.title)
                self.list.SetStringItem(item, 1, tab_title)
                self.list.SetItemData(item, terminal)

    def OnLeftDown(self, event):
        wx.CallAfter(self.text.SetFocus)
        event.Skip()

    def OnSelect(self, event):
        terminal = self.list.GetItemData(self.list.GetFirstSelected())
        tab = terminal.GetParentTab()

        tab.GetParent().SetSelection(tab.GetParent().GetPageIndex(tab))
        self.app.focus_terminal(terminal, False)

        wx.CallAfter(self.text.SetFocus)

    def OnKeyDown(self, event):
        keycode = event.GetKeyCode()

        if keycode == wx.WXK_UP:
            self.list.Select(
                (self.list.GetFirstSelected() - 1) % self.list.GetItemCount())
        elif keycode == wx.WXK_DOWN:
            self.list.Select((self.list.GetFirstSelected() + 1) %
                             self.list.GetItemCount())
        elif keycode == wx.WXK_ESCAPE:
            self.Hide()
        else:
            event.Skip()

    def OnItemActivated(self, event):
        self.Hide()


class EventThread(threading.Thread):
    def __init__(self, app):
        super(EventThread, self).__init__()
        self.app = app
        self.daemon = True

    def run(self):
        while 1:
            if win32event.WaitForSingleObject(
                    self.app.new_window_event,
                    win32event.INFINITE) == win32event.WAIT_OBJECT_0:
                wx.CallAfter(self.app.spawn_window)

class MoveWindowThread(threading.Thread):
    def __init__(self, app):
        super(MoveWindowThread, self).__init__()
        self.app = app
        self.daemon = True
        self.request_queue = Queue.Queue()

    def run(self):
        while 1:
            terminals = {}
            terminals[self.request_queue.get(True)] = True
            for i in xrange(self.request_queue.qsize()):
                terminals[self.request_queue.get()] = True

            for terminal in terminals.iterkeys():
                size = terminal.GetSize()
                # Minimum size of 100x100, really small sizes messes up the terminal
                win32gui.MoveWindow(terminal.terminal_hwnd, 0, 20, max(
                    size[0], 100), max(size[1] - 20, 100), True)

            time.sleep(0.05)



class SvanTerm(wx.App):

    def OnInit(self):
        self.new_window_event = win32event.CreateEvent(
            None, 0, 0, "SvanTerm_new_window")
        if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
            # An instance already exists, send an open new window event instead
            win32event.SetEvent(self.new_window_event)
            return False

        self.spawn_terminal()
        self.event_tread = EventThread(self)
        self.event_tread.start()
        self.move_window_thread = MoveWindowThread(self)
        self.move_window_thread.start()
        self.find_dialog = FindDialog(self)

        self.hwnd_to_terminal_window = {}
        self.hwnd_to_terminal = {}
        self.dock_from = None
        self.last_active_terminal = None
        self.clicked_terminal = None
        self.spawn_window()

        self.terminal_event_cfunc = CFUNCTYPE(c_voidp, c_int, c_int, c_int,
                                              c_int, c_int, c_int,
                                              c_int)(self.OnTerminalEvent)

        self.terminal_event_hook = windll.user32.SetWinEventHook(
            win32con.EVENT_SYSTEM_FOREGROUND, win32con.EVENT_OBJECT_NAMECHANGE,
            0, self.terminal_event_cfunc, 0, 0, 0)

        self.dock_hint = wx.Frame(None, style=wx.STAY_ON_TOP)
        self.dock_hint.SetTransparent(127)

        # Use a keyboard hook instead of regular (hot)keys to filter out
        # Ctrl-Shift-<char> from triggering thrash characters in mintty
        self.keyboard_hook_pointer = CFUNCTYPE(
            c_int, c_int, c_int, POINTER(c_void_p))(self.Keyboard_Event)
        self.keyboard_hook = user32.SetWindowsHookExA(
            win32con.WH_KEYBOARD_LL, self.keyboard_hook_pointer, None, 0)

        self.mouse_hook_pointer = CFUNCTYPE(
            c_int, c_int, c_int, POINTER(c_void_p))(self.Mouse_Event)
        self.mouse_hook = user32.SetWindowsHookExA(
            win32con.WH_MOUSE_LL, self.mouse_hook_pointer, None, 0)

        return True

    def spawn_terminal(self):
        self.cached_terminal = subprocess.Popen(
            [r'c:\cygwin64\bin\mintty.exe', "-whide", "-"])

    def Keyboard_Event(self, nCode, wParam, lParam):
        lst = cast(lParam, POINTER(c_int))
        keycode = lst[0]

        if (wParam == win32con.WM_KEYDOWN and
           (win32api.GetAsyncKeyState(win32con.VK_LCONTROL) & 0x8000) and
           (win32api.GetAsyncKeyState(win32con.VK_LSHIFT) & 0x8000)):
            try:
                hwnd = win32gui.GetForegroundWindow()
                if ((keycode >= ord("A") and keycode <= ord("Z") or
                    (keycode >= win32con.VK_F1 and keycode <= win32con.VK_F12))
                        and hwnd in self.hwnd_to_terminal_window):
                    self.process_hotkey(
                        keycode, self.hwnd_to_terminal_window[hwnd])
                    return -1

            except wx._core.PyDeadObjectError:
                pass

        # Broadcast to terminals (not yet working)
        # hwnd = win32gui.GetForegroundWindow()
        # if hwnd in self.hwnd_to_terminal_window:
        #     for terminal in self.build_terminal_list(
        #            self.hwnd_to_terminal_window[hwnd].tabs.GetCurrentPage()):
        #         # win32gui.SetFocus(terminal.terminal_hwnd)
        #         # win32api.keybd_event(keycode, 255, 0)

        #         print keycode
        #         win32api.PostMessage(terminal.terminal_hwnd,
        #                              wParam, lParam, 0)
        #         if keycode not in [win32con.VK_LCONTROL, win32con.VK_LSHIFT]:
        #             win32api.PostMessage(terminal.terminal_hwnd,
        #                                  win32con.WM_CHAR, keycode, 0)
        #     return -1

        return user32.CallNextHookEx(0, nCode, wParam, lParam)

    def Mouse_Event(self, nCode, wParam, lParam):
        if (not wParam in [win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP] and
                not (wParam == win32con.WM_MOUSEMOVE and self.dock_from)):
            return user32.CallNextHookEx(0, nCode, wParam, lParam)

        lst = cast(lParam, POINTER(c_int))
        x = lst[0]
        y = lst[1]

        win = wx.FindWindowAtPoint((x, y))

        if wParam == win32con.WM_LBUTTONDOWN:
            if isinstance(win, TerminalHeader):
                self.InitiateDragDrop(win.GetParent())

            if isinstance(win, Terminal):
                self.clicked_terminal = win
                self.focus_terminal(win, False)

            if not isinstance(win,
                              (ultimatelistctrl.UltimateListMainWindow,
                               wx.TextCtrl)):
                self.find_dialog.Hide()

        if self.dock_from:
            if wParam == win32con.WM_LBUTTONUP:
                self.FinishDragDrop()
            else:
                if isinstance(win, aui.auibook.AuiTabCtrl):
                    self.dock_hint.SetRect(win.GetScreenRect())
                    self.dock_to = win
                    if isinstance(self.dock_from, Terminal):
                        win.GetParent().ActivateTabAtPoint(x, y)
                elif win == self.dock_hint:
                    if self.dock_to == DOCK_NEW_WINDOW:
                        self.dock_hint.SetRect((x + 1, y + 1, 800, 600))
                    elif (isinstance(self.dock_to, aui.auibook.AuiTabCtrl) and
                            isinstance(self.dock_from, Terminal)):
                        self.dock_to.GetParent().ActivateTabAtPoint(x, y)
                    elif isinstance(self.dock_to, Terminal):
                        self.dock_to.ShowDockHint(
                            self.dock_to.ScreenToClient((x, y)))
                elif win is None or isinstance(self.dock_from, Container):
                    self.dock_to = DOCK_NEW_WINDOW
                    self.dock_hint.SetRect((x + 1, y + 1, 800, 600))
                elif isinstance(win, Terminal):
                    win.ShowDockHint(win.ScreenToClient((x, y)))
                elif isinstance(win, TerminalHeader):
                    win.GetParent().ShowDockHint(
                        win.GetParent().ScreenToClient((x, y)))

        if wParam == win32con.WM_LBUTTONUP and self.clicked_terminal:
            self.focus_terminal(self.clicked_terminal, True)
            self.clicked_terminal = None

        return user32.CallNextHookEx(0, nCode, wParam, lParam)

    def unfocus_terminal(self, terminal):
        try:
            terminal.text.enabled = False
            terminal.text.Refresh()
        except (wx._core.PyDeadObjectError, AttributeError):
            pass

    def focus_terminal(self, terminal, set_focus=True, verify_foreground_window=None):
        if terminal != self.last_active_terminal:
            self.unfocus_terminal(self.last_active_terminal)
            self.last_active_terminal = terminal

        if not self.dock_from:
            terminal.text.enabled = True
            terminal.text.Refresh()

        terminal.GetParentTab().active_terminal = terminal

        if set_focus:
            wx.CallAfter(self.set_focus, terminal.terminal_hwnd, verify_foreground_window)

        self.update_title(terminal.terminal_hwnd)

    def set_focus(self, hwnd, verify_foreground_window=None):
        if (verify_foreground_window and not
                win32gui.GetForegroundWindow() == verify_foreground_window):
            return

        win32gui.SetFocus(hwnd)

    def process_hotkey(self, keycode, window):
        active_terminal = window.tabs.GetCurrentPage().active_terminal

        if keycode >= win32con.VK_F1 and keycode <= win32con.VK_F12:
            index = keycode - win32con.VK_F1

            if index < window.tabs.GetPageCount():
                window.tabs.SetSelection(index)

        elif keycode == ord("T"):
            new_tab = Container(window.tabs, self, window.tabs.GetClientSize())
            new_terminal = Terminal(new_tab, self)
            window.tabs.AddTab(new_tab, new_terminal.title.ljust(8, " ")[:20])
            self.focus_terminal(new_terminal)

        elif keycode == ord("H") or keycode == ord("V"):
            new_splitter = Splitter(active_terminal.GetParent(), self)

            if keycode == ord("H"):
                new_splitter.SplitHorizontally(
                    new_splitter.panel1, new_splitter.panel2)
            else:
                new_splitter.SplitVertically(
                    new_splitter.panel1, new_splitter.panel2)

            self.focus_terminal(Terminal(new_splitter.panel2, self))
            new_splitter.Show()
            active_terminal.Reparent(new_splitter.panel1)
            new_splitter.panel1.OnSize()

        elif keycode == ord("C"):
            active_terminal.Destroy()

        elif keycode in [ord("Z"), ord("X"), ord("A"), ord("S")]:
            child = active_terminal
            while isinstance(child.GetGrandParent(), Splitter):
                splitter = child.GetGrandParent()

                if ((splitter.GetSplitMode() == wx.SPLIT_HORIZONTAL and
                        keycode in [ord("A"), ord("S")]) or
                    (splitter.GetSplitMode() == wx.SPLIT_VERTICAL
                        and keycode in [ord("Z"), ord("X")])):
                    child = splitter
                    continue

                if ((keycode in [ord("Z"), ord("A")]
                    and child.GetParent() == splitter.panel1)
                    or (keycode in [ord("X"), ord("S")]
                        and child.GetParent() == splitter.panel2)):
                    splitter.SetSashPosition(splitter.GetSashPosition() - 50)
                    break
                else:
                    splitter.SetSashPosition(splitter.GetSashPosition() + 50)
                    break

        elif keycode == ord("J") or keycode == ord("K"):
            terminal_list = self.build_terminal_list(
                window.tabs.GetCurrentPage())
            terminal_index = terminal_list.index(active_terminal)

            if keycode == ord("J"):
                self.focus_terminal(
                    terminal_list[(terminal_index - 1) % len(terminal_list)])
            else:
                self.focus_terminal(
                    terminal_list[(terminal_index + 1) % len(terminal_list)])

        elif keycode == ord("O") or keycode == ord("P"):
            hwnd_list = self.hwnd_to_terminal_window.keys()
            window_index = hwnd_list.index(window.GetHandle())

            if keycode == ord("O"):
                win32gui.SetForegroundWindow(
                    hwnd_list[(window_index - 1) % len(hwnd_list)])
            else:
                win32gui.SetForegroundWindow(
                    hwnd_list[(window_index + 1) % len(hwnd_list)])

        elif keycode == ord("W"):
            window.tabs.GetCurrentPage().Hide()
            window.tabs.GetCurrentPage().Destroy()

        elif keycode == ord("U"):
            window.tabs.AdvanceSelection(False)

        elif keycode == ord("I"):
            window.tabs.AdvanceSelection(True)

        elif keycode == ord("R"):
            window.tabs.EditTab(window.tabs.GetSelection())
            window.tabs.FindFocus().SelectAll()

        elif keycode == ord("N"):
            self.spawn_window()

        elif keycode == ord("F"):
            self.find_dialog.text.SetValue("")
            self.find_dialog.Filter()
            pos = window.GetPosition()
            win_size = window.GetSize()
            find_size = self.find_dialog.GetSize()

            self.find_dialog.SetPosition(
                (pos[0] + ((win_size[0] - find_size[0]) / 2),
                 pos[1] + ((win_size[1] - find_size[1]) / 2)))
            self.find_dialog.Show()

    def spawn_window(self):
        new_window = TerminalWindow(self)
        new_tab = Container(new_window.tabs, self)
        new_tab.active_terminal = Terminal(new_tab, self)
        new_window.tabs.AddTab(
            new_tab, new_tab.active_terminal.title.ljust(8, " ")[:20])
        self.update_title(new_tab.active_terminal.terminal_hwnd)

    def build_terminal_list(self, root):
        if not len(root.GetChildren()):
            return []

        child = root.GetChildren()[0]

        if isinstance(child, Terminal):
            return [child]
        elif isinstance(child, Splitter):
            terminal_list = self.build_terminal_list(child.panel1)
            terminal_list.extend(self.build_terminal_list(child.panel2))

        return terminal_list

    def OnTerminalEvent(self, hWinEventHook, eventType, hwnd, idObject,
                        idChild, dwEventThread, dwmsEventTime):
        if hwnd in self.hwnd_to_terminal:
            if eventType == win32con.EVENT_OBJECT_DESTROY and idObject == 0:
                self.hwnd_to_terminal[hwnd].Destroy()
            if eventType == win32con.EVENT_OBJECT_NAMECHANGE:
                self.update_title(hwnd)

        if (eventType == win32con.EVENT_SYSTEM_FOREGROUND and
                not self.find_dialog.IsShown()):
            try:
                if (not hwnd in self.hwnd_to_terminal and
                        not hwnd in self.hwnd_to_terminal_window and
                        not self.dock_from):
                    self.unfocus_terminal(self.last_active_terminal)

                if hwnd in self.hwnd_to_terminal_window:
                    terminal = self.hwnd_to_terminal_window[
                        hwnd].tabs.GetCurrentPage().active_terminal

                    # Check that there is no other window actually having the
                    # focus to prevent race conditions with queued events
                    if terminal and not self.clicked_terminal:
                        self.focus_terminal(terminal, verify_foreground_window=hwnd)

            except wx._core.PyDeadObjectError:
                pass

    def update_title(self, hwnd):
        title = win32gui.GetWindowText(hwnd)
        terminal = self.hwnd_to_terminal[hwnd]
        terminal.text.SetLabel(title)
        terminal.title = title

        tab = terminal.GetParentTab()
        if tab.active_terminal == terminal:
            if tab.custom_name == "":
                tab.GetParent().SetPageText(tab.GetParent().GetPageIndex(
                    tab), win32gui.GetWindowText(hwnd).ljust(8, " ")[:20])
            else:
                tab.GetParent().SetPageText(tab.GetParent().GetPageIndex(
                    tab), tab.custom_name)

            if tab.GetParent().GetCurrentPage() == tab:
                tab.GetGrandParent().SetTitle(title + " - " + PROGRAM_TITLE)

    def InitiateDragDrop(self, dock_from):
        if self.dock_from:
            return

        if isinstance(dock_from, Terminal):
            self.focus_terminal(dock_from)
            self.dock_from_tab = dock_from.GetParentTab()

        self.dock_from = dock_from
        self.dock_to = dock_from
        self.dock_hint.SetRect((0, 0, 0, 0))
        self.dock_hint.Show()

    def FinishDragDrop(self):
        wx.CallAfter(self.dock_hint.Hide)

        if self.dock_from == self.dock_to:
            self.dock_from = None
            return

        if isinstance(self.dock_from, Container):
            if (self.dock_to != DOCK_NEW_WINDOW and
                    self.dock_from in self.dock_to.GetParent().GetChildren()):
                self.dock_from = None
                return

            tabs = self.dock_from.GetParent()
            tabs.RemoveTab(self.dock_from)
            if self.dock_to == DOCK_NEW_WINDOW:
                window = TerminalWindow(self)
                window.SetPosition(wx.GetMousePosition())
                window.tabs.AddTab(
                    self.dock_from, self.dock_from.active_terminal.title)
            else:
                self.dock_to.GetParent().AddTab(
                    self.dock_from, self.dock_from.active_terminal.title)

            wx.CallAfter(self.focus_terminal, self.dock_from.active_terminal)
        else:
            terminal_list = self.build_terminal_list(self.dock_from_tab)
            terminal_index = terminal_list.index(self.dock_from)

            if len(terminal_list) > 1:
                if (self.dock_from.GetGrandParent().panel1 ==
                        self.dock_from.GetParent()):
                    self.dock_from_tab.active_terminal = terminal_list[
                        terminal_list.index(self.dock_from) + 1]
                else:
                    self.dock_from_tab.active_terminal = terminal_list[
                        terminal_list.index(self.dock_from) - 1]

            self.dock_from.GetParent().Hide()
            wx.CallAfter(self.dock_from.GetParent().Destroy)

            if (self.dock_to == DOCK_NEW_WINDOW or
                    isinstance(self.dock_to, aui.auibook.AuiTabCtrl)):
                if self.dock_to == DOCK_NEW_WINDOW:
                    window = TerminalWindow(self)
                    window.SetPosition(wx.GetMousePosition())
                else:
                    window = self.dock_to.GetGrandParent()

                new_tab = Container(window.tabs, self)
                new_tab.active_terminal = self.dock_from
                self.dock_from.Reparent(new_tab)
                window.tabs.AddTab(new_tab, self.dock_from.title)
                new_tab.OnSize()
            else:
                new_splitter = Splitter(self.dock_to.GetParent(), self)

                if self.dock_pos == DOCK_TOP or self.dock_pos == DOCK_BOTTOM:
                    new_splitter.SplitHorizontally(
                        new_splitter.panel1, new_splitter.panel2)
                else:
                    new_splitter.SplitVertically(
                        new_splitter.panel1, new_splitter.panel2)

                if self.dock_pos == DOCK_TOP or self.dock_pos == DOCK_LEFT:
                    self.dock_to.Reparent(new_splitter.panel2)
                    self.dock_from.Reparent(new_splitter.panel1)
                else:
                    self.dock_to.Reparent(new_splitter.panel1)
                    self.dock_from.Reparent(new_splitter.panel2)

                new_splitter.panel1.OnSize()
                new_splitter.panel2.OnSize()
                new_splitter.Show()

            wx.CallAfter(self.focus_terminal, self.dock_from)

        self.dock_from = None

app = SvanTerm(0)
app.MainLoop()

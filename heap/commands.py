# Copyright (C) 2010  David Hugh Malcolm
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import gdb
import re
import sys
import argparse

from heap.history import history, Snapshot, Diff

from heap import lazily_get_usage_list, \
    fmt_size, fmt_addr, \
    categorize, categorize_usage_list, Usage, \
    hexdump_as_bytes, \
    Table, \
    MissingDebuginfo


def need_debuginfo(f):
    def g(self, args, from_tty):
        try:
            return f(self, args, from_tty)
        except MissingDebuginfo as e:
            print('Missing debuginfo for %s' % e.module)
            print('Suggested fix:')
            print('    debuginfo-install %s' % e.module)
    return g


def target_running(f):
    def g(self, args, from_tty):
        try:
            return f(self, args, from_tty)
        except (gdb.error, NameError) as e:
            print("Gdb error: \"%s\". Is the target running?" % e)
            import traceback
            print()
            print(traceback.format_exc())
    return g


class Heap(gdb.Command):
    'Print a report on memory usage, by category'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap",
                              gdb.COMMAND_DATA,
                              prefix=True)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        total_by_category = {}
        count_by_category = {}
        total_size = 0
        total_count = 0
        try:
            usage_list = list(lazily_get_usage_list())
            for u in usage_list:
                u.ensure_category()
                total_size += u.size
                if u.category in total_by_category:
                    total_by_category[u.category] += u.size
                else:
                    total_by_category[u.category] = u.size

                total_count += 1
                if u.category in count_by_category:
                    count_by_category[u.category] += 1
                else:
                    count_by_category[u.category] = 1

        except KeyboardInterrupt:
            pass # FIXME

        t = Table(['Domain', 'Kind', 'Detail', 'Count', 'Allocated size'])
        for category in sorted(total_by_category.keys(),
                               key=total_by_category.get,
                               reverse=True):
            detail = category.detail
            if not detail:
                detail = ''
            t.add_row([category.domain,
                       category.kind,
                       detail,
                       fmt_size(count_by_category[category]),
                       fmt_size(total_by_category[category]),
                       ])
        t.add_row(['', '', 'TOTAL', fmt_size(total_count), fmt_size(total_size)])
        t.write(sys.stdout)
        print()

class HeapSizes(gdb.Command):
    'Print a report on memory usage, by sizes'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap sizes",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import glibc_arenas
        ms = glibc_arenas.get_ms()
        chunks_by_size = {}
        num_chunks = 0
        total_size = 0
        try:
            for chunk in ms.iter_chunks():
                if not chunk.is_inuse():
                    continue
                size = int(chunk.chunksize())
                num_chunks += 1
                total_size += size
                if size in chunks_by_size:
                    chunks_by_size[size] += 1
                else:
                    chunks_by_size[size] = 1
        except KeyboardInterrupt:
            pass # FIXME
        t = Table(['Chunk size', 'Num chunks', 'Allocated size'])
        for size in sorted(chunks_by_size.keys(), key=lambda x: chunks_by_size[x] * x):
            t.add_row([fmt_size(size),
                       chunks_by_size[size],
                       fmt_size(chunks_by_size[size] * size)])
        t.add_row(['TOTALS', num_chunks, fmt_size(total_size)])
        t.write(sys.stdout)
        print()


class HeapUsed(gdb.Command):
    'Print used heap chunks'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap used",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import glibc_arenas
        print('Used chunks of memory on heap')
        print('-----------------------------')
        ms = glibc_arenas.get_ms()
        try:
            for i, chunk in enumerate(ms.iter_chunks()):
                if not chunk.is_inuse():
                    continue
                size = chunk.chunksize()
                mem = chunk.as_mem()
                u = Usage(mem, size)
                category = categorize(u, None)
                hd = hexdump_as_bytes(mem, 32)
                print ('%6i: %s -> %s %8i bytes %20s |%s'
                       % (i,
                          fmt_addr(chunk.as_mem()),
                          fmt_addr(chunk.as_mem()+size-1),
                          size, category, hd))
        except KeyboardInterrupt:
            print("Interrupted")
        print()


class HeapFree(gdb.Command):
    'Print free heap chunks'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap free",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import glibc_arenas
        print('Free chunks of memory on heap')
        print('-----------------------------')
        ms = glibc_arenas.get_ms()
        total_size = 0

        for i, chunk in enumerate(ms.iter_free_chunks()):
            size = chunk.chunksize()
            total_size += size
            mem = chunk.as_mem()
            u = Usage(mem, size)
            category = categorize(u, None)
            hd = hexdump_as_bytes(mem, 32)

            print ('%6i: %s -> %s %8i bytes %20s |%s'
                   % (i,
                      fmt_addr(chunk.as_mem()),
                      fmt_addr(chunk.as_mem()+size-1),
                      size, category, hd))

        print("Total size: %s" % total_size)


class HeapAll(gdb.Command):
    'Print all heap chunks'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap all",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import glibc_arenas
        print('All chunks of memory on heap (both used and free)')
        print('-------------------------------------------------')
        ms = glibc_arenas.get_ms()
        for i, chunk in enumerate(ms.iter_chunks()):
            size = chunk.chunksize()
            if chunk.is_inuse():
                kind = ' inuse'
            else:
                kind = ' free'

            print ('%i: %s -> %s %s: %i bytes (%s)'
                   % (i,
                      fmt_addr(chunk.as_address()),
                      fmt_addr(chunk.as_address()+size-1),
                      kind, size, chunk))
        print()

class HeapLog(gdb.Command):
    'Print a log of recorded heap states'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap log",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        h = history
        if len(h.snapshots) == 0:
            print('(no history)')
            return
        for i in range(len(h.snapshots), 0, -1):
            s = h.snapshots[i-1]
            print('Label %i "%s" at %s' % (i, s.name, s.time))
            print('    ', s.summary())
            if i > 1:
                prev = h.snapshots[i-2]
                d = Diff(prev, s)
                print()
                print('    ', d.stats())
            print()

class HeapLabel(gdb.Command):
    'Record the current state of the heap for later comparison'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap label",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        s = history.add(args)
        print(s.summary())


class HeapDiff(gdb.Command):
    'Compare two states of the heap'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap diff",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        h = history
        if len(h.snapshots) == 0:
            print('(no history)')
            return
        prev = h.snapshots[-1]
        curr = Snapshot.current('current')
        d = Diff(prev, curr)
        print('Changes from %s to %s' % (prev.name, curr.name))
        print('  ', d.stats())
        print()
        print('\n'.join(['  ' + line for line in d.as_changes().splitlines()]))

class HeapSelect(gdb.Command):
    'Query used heap chunks'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap select",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.query import do_query
        from heap.parser import ParserError
        try:
            do_query(args)
        except ParserError as e:
            print(e)

class HeapSearch(gdb.Command):
    'Search for address in heap'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap search",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import glibc_arenas

        arg_list = gdb.string_to_argv(args)

        parser = argparse.ArgumentParser(add_help=True, usage="heap search [-a] [-b] <ADDR>")
        parser.add_argument('addr', metavar='ADDR', type=str, nargs=1, help="Target address")
        parser.add_argument('-b', dest='before', action="store_true", default=False, help="Show chunk before")
        parser.add_argument('-a', dest='after', action="store_true", default=False, help="Show chunk after")

        try:
            args_dict = parser.parse_args(args=arg_list)
        except:
            return

        addr_arg = args_dict.addr[0]

        if addr_arg.startswith("0x"):
            addr = int(addr_arg, 16)
        else:
            addr = int(addr_arg)
        
        print('search heap for address %s' % hex(addr))
        print('-------------------------------------------------')
        ms = glibc_arenas.get_ms()
        output_str = ""
        for i, chunk in enumerate(ms.iter_chunks()):
            
            size = chunk.chunksize()
            if addr >= chunk.as_address() and addr < chunk.as_address() + size:
                if chunk.is_inuse():
                    kind = ' inuse'
                else:
                    kind = ' free'

                output_str += 'BLOCK:\t%s -> %s %s: \n\t%i bytes (%s)\n' % (
                          fmt_addr(chunk.as_address()),
                          fmt_addr(chunk.as_address()+size-1),
                          kind, size, chunk)
                if args_dict.after:
                    chunk_after = chunk.next_chunk()
                    if chunk.is_inuse():
                        kind = ' inuse'
                    else:
                        kind = ' free'
                    output_str += 'NEXT:\t%s -> %s %s: \n\t%i bytes (%s)\n' % (
                        fmt_addr(chunk_after.as_address()),
                        fmt_addr(chunk_after.as_address()+size-1),
                        kind, chunk_after.chunksize(), chunk_after)
        print(output_str)

class HeapChunk(gdb.Command):
    'Not implemented'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap chunk",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        print(args)
        arg_list = gdb.string_to_argv(args)
        print(arg_list)


class Objdump(gdb.Command):
    'Try to detect if ADDR is an object and dump it'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "objdump",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import iter_code_sections
        from heap import WrappedPointer,caching_lookup_type
        arg_list = gdb.string_to_argv(args)
        parser = argparse.ArgumentParser(add_help=True, usage="objdump [-s SIZE] <ADDR>")
        parser.add_argument('addr', metavar='ADDR', type=str, nargs=1, help="Target address")
        parser.add_argument('-s', dest='size', default=None, help='Total dump size')
        
        try:
            args_dict = parser.parse_args(args=arg_list)
        except:
            return

        addr_arg = args_dict.addr[0]
        if addr_arg.startswith('0x'):
            addr = int(addr_arg, 16)
        else:
            addr = int(addr_arg)

        if args_dict.size:
            if args_dict.size.startswith('0x'):
                total_size = int(args_dict.size, 16)
            else:
                total_size = int(args_dict.size)
        else:
            total_size = 0x10

        print('Searching in the following executable sections'
        print('-------------------------------------------------')
        text = [] #list of pairs (start, end) of a code section
        for i in gdb.inferiors():
            for r in iter_code_sections(i.pid):
                print("%s - %s : %s" % (hex(r[0]), hex(r[1]), r[2]))
                text.append((r[0], r[1], r[2]))

        print('\nDumping Object at address %s' % hex(addr))
        print('-------------------------------------------------')
        SIZE_SZ = caching_lookup_type('size_t').sizeof
        for a in range(addr,addr+total_size, SIZE_SZ):
            ptr = WrappedPointer(gdb.Value(a))
            #dereference first, at the first access denied bail out, dont go further
            try:
                val = ptr.dereference()
                print("%s => %s" % (hex(ptr), hex(val)))
                for t in text:
                    if a >= t[0] and a <t[1]:
                        place=0
            
            except:
                print("Error accessing memory")
                raise


class Hexdump(gdb.Command):
    'Print a hexdump, starting at the specific region of memory'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "hexdump",
                              gdb.COMMAND_DATA)

    def invoke(self, args, from_tty):
        
        arg_list = gdb.string_to_argv(args)
        parser = argparse.ArgumentParser(add_help=True, usage="hexdump [-c] [-w] [-s SIZE] <ADDR>")
        parser.add_argument('addr', metavar='ADDR', type=str, nargs=1, help="Target address")
        parser.add_argument('-c', dest='chars', action="store_true", default=False, help="Show chars only")
        parser.add_argument('-s', dest='size', default=None, help='Total Dump size')
        parser.add_argument('-w', dest='wide', action="store_true", default=False, 
            help='wide: 32 bytes per line instead of 16')

        try:
            args_dict = parser.parse_args(args=arg_list)
        except:
            return

        addr_arg = args_dict.addr[0]
        if args_dict.size:
            if args_dict.size.startswith('0x'):
                total_size = int(args_dict.size, 16)
            else:
                total_size = int(args_dict.size)
        else:
            total_size = 0x100

        if args_dict.wide:
            size = 32
        else:
            size = 16

        chars_only = args_dict.chars


        if addr_arg.startswith('0x'):
            start = int(addr_arg, 16)
        else:
            start = int(addr_arg)

        addr = start
        end = addr + total_size
        try:
            while addr + size <= end:
                hd = hexdump_as_bytes(addr, size, chars_only=chars_only)
                print ('%s -> %s %s' % (fmt_addr(addr), fmt_addr(addr + size -1), hd))
                addr += size
            
            r = (end-start) % size
            if r > 0 :
                hd = hexdump_as_bytes(addr, r, chars_only=chars_only)
                print ('%s -> %s %s' % (fmt_addr(addr), fmt_addr(addr + r -1), hd))
        except KeyboardInterrupt:
            print("Interrupt")
            return
        except gdb.MemoryError:
            print("Error accessing memory")

class HeapArenas(gdb.Command):
    'Display heap arenas available'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap arenas",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import glibc_arenas
        for n, arena in enumerate(glibc_arenas.arenas):
            print("Arena #%d: %s" % (n, arena.address))

class HeapArenaSelect(gdb.Command):
    'Select heap arena'
    def __init__(self):
        gdb.Command.__init__ (self,
                              "heap arena",
                              gdb.COMMAND_DATA)

    @need_debuginfo
    @target_running
    def invoke(self, args, from_tty):
        from heap.glibc import glibc_arenas
        arena_num = int(args)
        glibc_arenas.cur_arena = glibc_arenas.arenas[arena_num]
        print("Arena set to %s" % glibc_arenas.cur_arena.address)



def register_commands():
    # Register the commands with gdb
    Heap()
    HeapSizes()
    HeapUsed()
    HeapFree()
    HeapAll()
    HeapLog()
    HeapLabel()
    HeapDiff()
    HeapSelect()
    HeapArenas()
    HeapArenaSelect()
    HeapSearch()
    HeapChunk()
    Hexdump()
    Objdump()

    from heap.cpython import register_commands as register_cpython_commands
    register_cpython_commands()

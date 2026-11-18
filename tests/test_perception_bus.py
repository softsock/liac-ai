import asyncio
import unittest
from dataclasses import replace

from tests._fixtures import perception
from vtuber.runtime.perception_bus import PerceptionBus, PerceptionQueueFull


class PerceptionBusTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_burst_resets_quiet_gap(self):
        bus = PerceptionBus(text_gap=.12, max_window=1)
        await bus.publish(perception('1'))
        drain = asyncio.create_task(bus.drain())
        await asyncio.sleep(.07)
        await bus.publish(perception('2'))
        await asyncio.sleep(.07)
        self.assertFalse(drain.done())
        await bus.publish(perception('3'))
        batch = await asyncio.wait_for(drain, .5)
        self.assertEqual([p.perception_id for p in batch.items], ['1', '2', '3'])
        self.assertEqual(batch.closed_by, 'quiet')

    async def test_stream_closes_at_first_arrival_ceiling(self):
        bus = PerceptionBus(text_gap=.2, max_window=.12)
        await bus.publish(perception('0'))
        async def feed():
            for i in range(1, 20):
                await asyncio.sleep(.02)
                await bus.publish(perception(str(i)))
        producer = asyncio.create_task(feed())
        try:
            batch = await asyncio.wait_for(bus.drain(), .35)
            self.assertEqual(batch.closed_by, 'max_window')
            self.assertFalse(producer.done())
            self.assertEqual(batch.items[0].perception_id, '0')
            await producer
            await bus.close()
            items = list(batch.items)
            while (later := await bus.drain()) is not None:
                items.extend(later.items)
            self.assertEqual([p.perception_id for p in items], [str(i) for i in range(20)])
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def test_keys_never_mix(self):
        bus = PerceptionBus(text_gap=.02)
        for item in [perception('a'), perception('b', conversation_key='other'), perception('c')]:
            await bus.publish(item)
        async with asyncio.timeout(1):
            first, second = await bus.drain(), await bus.drain()
        self.assertEqual([p.perception_id for p in first.items], ['a', 'c'])
        self.assertEqual([p.perception_id for p in second.items], ['b'])
        self.assertEqual(second.conversation_key, 'other')

    async def test_mixed_live_shortens_gap(self):
        bus = PerceptionBus(live_gap=.02, text_gap=1, max_window=2)
        await bus.publish(perception('chat'))
        drain = asyncio.create_task(bus.drain())
        await asyncio.sleep(.01)
        await bus.publish(perception('live', kind='observation', delivery='ambient'))
        await bus.publish(perception('later-chat'))
        batch = await asyncio.wait_for(drain, .4)
        self.assertEqual([p.perception_id for p in batch.items], ['chat', 'live', 'later-chat'])
        self.assertEqual(batch.closed_by, 'quiet')

    async def test_mixed_gap_never_lengthens_in_either_order(self):
        for kinds in [('chat', 'observation'), ('observation', 'chat')]:
            with self.subTest(kinds=kinds):
                bus = PerceptionBus(text_gap=.02, live_gap=1)
                for i, kind in enumerate(kinds):
                    await bus.publish(perception(str(i), kind=kind))
                batch = await asyncio.wait_for(bus.drain(), .3)
                self.assertEqual(len(batch.items), 2)

    async def test_idle_backlog_does_not_wait_extra_gap(self):
        bus = PerceptionBus(text_gap=.08)
        await bus.publish(perception())
        await asyncio.sleep(.12)
        self.assertEqual(len((await asyncio.wait_for(bus.drain(), .05)).items), 1)

    async def test_backlog_keeps_expired_windows_separate(self):
        bus = PerceptionBus(text_gap=.03)
        await bus.publish(perception('old'))
        await asyncio.sleep(.06)
        await bus.publish(perception('new'))
        self.assertEqual([p.perception_id for p in (await bus.drain()).items], ['old'])
        await bus.close()
        self.assertEqual([p.perception_id for p in (await bus.drain()).items], ['new'])

    async def test_duplicate_idempotent(self):
        bus = PerceptionBus(text_gap=0, max_pending=1)
        item = perception()
        self.assertTrue(await bus.publish(item))
        self.assertFalse(await bus.publish(item))
        with self.assertRaises(ValueError):
            await bus.publish(replace(item, content='conflict'))
        self.assertEqual((await bus.drain()).items, (item,))
        self.assertEqual(bus.stats['duplicate'], 1)
        self.assertTrue(await bus.publish(item))

    async def test_noise_does_not_starve_direct(self):
        bus = PerceptionBus(text_gap=.04, max_pending=1)
        for i in range(300):
            self.assertFalse(await bus.publish(perception(str(i), kind='state', delivery='noise')))
        self.assertTrue(await bus.publish(perception('direct')))
        async def noise():
            for i in range(20):
                await asyncio.sleep(.005)
                await bus.publish(perception(f'n{i}', delivery='noise'))
        producer = asyncio.create_task(noise())
        try:
            batch = await asyncio.wait_for(bus.drain(), .3)
            self.assertEqual([p.perception_id for p in batch.items], ['direct'])
            await producer
            self.assertEqual(bus.stats['noise_dropped'], 320)
            self.assertEqual(bus.stats['overflow'], 0)
        finally:
            producer.cancel()
            await asyncio.gather(producer, return_exceptions=True)

    async def test_full_queue_rejects_meaningful(self):
        bus = PerceptionBus(text_gap=0, max_pending=1)
        await bus.publish(perception('first'))
        for delivery in ('direct', 'ambient'):
            with self.assertRaises(PerceptionQueueFull):
                await bus.publish(perception('retry', delivery=delivery))
        self.assertEqual((await bus.drain()).items[0].perception_id, 'first')
        self.assertTrue(await bus.publish(perception('retry')))
        self.assertEqual(bus.stats['overflow'], 2)
        self.assertEqual(bus.stats['published'], 2)
        self.assertEqual(bus.stats['batches'], 1)
        snapshot = bus.stats
        snapshot['published'] = -1
        self.assertEqual(bus.stats['published'], 2)

    async def test_close_drains_then_unblocks(self):
        bus = PerceptionBus(text_gap=100)
        await bus.publish(perception())
        drain = asyncio.create_task(bus.drain())
        await asyncio.sleep(0)
        await bus.close()
        self.assertEqual((await asyncio.wait_for(drain, .3)).closed_by, 'immediate')
        self.assertIsNone(await bus.drain())
        with self.assertRaises(RuntimeError):
            await bus.publish(perception('late'))
        empty = PerceptionBus()
        waiting = asyncio.create_task(empty.drain())
        await asyncio.sleep(0)
        await empty.close()
        self.assertIsNone(await asyncio.wait_for(waiting, .3))
        await empty.close()

    async def test_cancelled_drain_keeps_pending(self):
        bus = PerceptionBus(text_gap=100, max_pending=2)
        await bus.publish(perception('first'))
        drain = asyncio.create_task(bus.drain())
        await asyncio.sleep(0)
        await bus.publish(perception('second'))
        with self.assertRaises(PerceptionQueueFull):
            await bus.publish(perception('overflow'))
        drain.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await drain
        await bus.close()
        self.assertEqual([p.perception_id for p in (await bus.drain()).items], ['first', 'second'])
        self.assertIsNone(await bus.drain())

    async def test_concurrent_drains_do_not_steal_items(self):
        bus = PerceptionBus(text_gap=.02)
        await bus.publish(perception('a'))
        await bus.publish(perception('b', conversation_key='other'))
        async with asyncio.timeout(1):
            batches = await asyncio.gather(bus.drain(), bus.drain())
        self.assertEqual([[p.perception_id for p in b.items] for b in batches], [['a'], ['b']])

    def test_invalid_configuration(self):
        for field in ('live_gap', 'text_gap', 'max_window'):
            for value in (-1, float('nan'), float('inf'), None, '1', True):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    PerceptionBus(**{field: value})
        for value in (0, -1, 1.5, None, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PerceptionBus(max_pending=value)

import { useEffect } from 'react';
import { useProvince } from '@/lib/province';
import { pushSupported, syncPushContext } from '@/lib/push';
import { useMyStation } from '@/lib/station';

/** Держит сервер уведомлений в курсе: провинция и станция у дома (для сбоев на ней). Ничего не рисует. */
function Sync() {
  const { province } = useProvince();
  const my = useMyStation();
  const [code, name] = my.st;
  useEffect(() => {
    if (province) syncPushContext({ province: province.id, station: code, stationName: name });
  }, [province, code, name]);
  return null;
}

export function PushSync() {
  return pushSupported ? <Sync /> : null;
}
